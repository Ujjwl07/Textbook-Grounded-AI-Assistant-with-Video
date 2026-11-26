import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# While MongoDB is unreachable, try to reconnect at most this often, so a burst
# of requests does not each wait out a 5-second connection timeout.
RECONNECT_INTERVAL_SECONDS = 5.0


class DatabaseUnavailable(RuntimeError):
    """MongoDB cannot be reached right now. Answered as HTTP 503, not a crash."""


class DatabaseManager:
    """Manage MongoDB database operations for persistence."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.enabled = False
        self._connect_lock: Optional[asyncio.Lock] = None
        self._last_attempt = 0.0

    async def connect(self) -> None:
        self._last_attempt = time.monotonic()
        if self.client is not None and not self.enabled:
            self.client.close()  # left over from a failed attempt
            self.client = None
        try:
            self.client = AsyncIOMotorClient(self.settings.mongodb_uri, serverSelectionTimeoutMS=5000)
            await self.client.admin.command("ping")
            self.db = self.client[self.settings.mongodb_db_name]
            
            await self.db.users.create_index("email", unique=True)
            await self.db.users.create_index("clerk_id", unique=True, sparse=True)
            await self.db.videos.create_index("job_id", unique=True)
            await self.db.videos.create_index([("user_id", 1), ("created_at", -1)])
            await self.db.quiz_questions.create_index("question_id", unique=True)
            await self.db.quiz_questions.create_index("quiz_id")
            await self.db.quizzes.create_index("quiz_id", unique=True)
            await self.db.quiz_attempts.create_index([("user_id", 1), ("created_at", -1)])
            await self.db.admins.create_index("email", unique=True)
            
            await self.setup_admin_seed()
            self.enabled = True
            logger.info("MongoDB connected successfully.")
        except Exception as exc:
            self.enabled = False
            logger.error(f"MongoDB connection failed: {exc}")

    async def close(self) -> None:
        if self.client:
            self.client.close()

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        await self._ensure_db()
        user = await self.db.users.find_one({"email": email.lower().strip()}, {"_id": 0})
        if user:
            user["is_admin"] = await self.is_user_admin(user["email"])
        return user

    async def get_user_by_clerk_id(self, clerk_id: str) -> Optional[dict]:
        await self._ensure_db()
        user = await self.db.users.find_one({"clerk_id": clerk_id}, {"_id": 0})
        if user:
            user["is_admin"] = await self.is_user_admin(user["email"])
        return user

    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        await self._ensure_db()
        user = await self.db.users.find_one({"id": user_id}, {"_id": 0})
        if user:
            user["is_admin"] = await self.is_user_admin(user["email"])
        return user

    async def setup_admin_seed(self) -> None:
        count = await self.db.admins.count_documents({})
        if count == 0:
            await self.db.admins.insert_one({"email": "admin@admin.com", "created_at": datetime.utcnow()})

    async def is_user_admin(self, email: str) -> bool:
        await self._ensure_db()
        admin = await self.db.admins.find_one({"email": email.lower().strip()})
        return bool(admin)

    async def add_admin(self, email: str) -> None:
        await self._ensure_db()
        await self.db.admins.update_one(
            {"email": email.lower().strip()},
            {"$set": {"email": email.lower().strip(), "created_at": datetime.utcnow()}},
            upsert=True
        )

    async def create_user(self, user: dict) -> None:
        await self._ensure_db()
        await self.db.users.insert_one(user)

    async def update_user(self, user_id: str, updates: dict) -> None:
        await self._ensure_db()
        await self.db.users.update_one(
            {"id": user_id},
            {"$set": {**updates, "updated_at": datetime.utcnow()}},
        )

    async def save_video_record(self, record: dict) -> None:
        await self._ensure_db()
        await self.db.videos.update_one(
            {"job_id": record["job_id"]},
            {"$set": {**record, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    async def get_video_record(self, job_id: str) -> Optional[dict]:
        await self._ensure_db()
        return await self.db.videos.find_one({"job_id": job_id}, {"_id": 0})

    async def list_user_videos(self, user_id: str, limit: int = 20) -> list[dict]:
        await self._ensure_db()
        cursor = self.db.videos.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_video_by_filename(self, filename: str) -> Optional[dict]:
        await self._ensure_db()
        return await self.db.videos.find_one({"local_filename": filename}, {"_id": 0})

    async def update_video_record(self, job_id: str, fields: dict) -> None:
        await self._ensure_db()
        await self.db.videos.update_one({"job_id": job_id}, {"$set": fields})

    async def get_lesson_progress(self, user_id: str, job_id: str) -> dict:
        """A student's own state for one lesson: completed, saved and notes."""
        await self._ensure_db()
        doc = await self.db.lesson_progress.find_one({"user_id": user_id, "job_id": job_id}, {"_id": 0})
        return doc or {}

    async def update_lesson_progress(self, user_id: str, job_id: str, fields: dict) -> dict:
        await self._ensure_db()
        await self.db.lesson_progress.update_one(
            {"user_id": user_id, "job_id": job_id},
            {"$set": {**fields, "updated_at": datetime.utcnow()},
             "$setOnInsert": {"created_at": datetime.utcnow()}},
            upsert=True,
        )
        return await self.get_lesson_progress(user_id, job_id)

    async def get_quiz_question(self, question_id: str) -> Optional[dict]:
        await self._ensure_db()
        return await self.db.quiz_questions.find_one({"question_id": question_id}, {"_id": 0})

    async def save_quiz(self, quiz: dict, questions: list) -> None:
        """Store a generated quiz and its questions (answers included)."""
        await self._ensure_db()
        now = datetime.utcnow()
        await self.db.quizzes.insert_one({**quiz, "created_at": now})
        if questions:
            await self.db.quiz_questions.insert_many(
                [{**question, "created_at": now} for question in questions]
            )

    async def get_quiz(self, quiz_id: str) -> Optional[dict]:
        await self._ensure_db()
        return await self.db.quizzes.find_one({"quiz_id": quiz_id}, {"_id": 0})

    async def get_quiz_questions(self, quiz_id: str) -> list[dict]:
        await self._ensure_db()
        cursor = self.db.quiz_questions.find({"quiz_id": quiz_id}, {"_id": 0}).sort("created_at", 1)
        return await cursor.to_list(length=100)

    async def get_quiz_attempt(self, attempt_id: str) -> Optional[dict]:
        await self._ensure_db()
        return await self.db.quiz_attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})

    async def get_attempts_for_quiz(self, user_id: str, quiz_id: str) -> list[dict]:
        await self._ensure_db()
        cursor = self.db.quiz_attempts.find({"user_id": user_id, "quiz_id": quiz_id}, {"_id": 0})
        return await cursor.to_list(length=100)

    async def save_quiz_attempt(self, attempt: dict) -> None:
        await self._ensure_db()
        await self.db.quiz_attempts.insert_one({**attempt, "created_at": datetime.utcnow()})

    async def update_quiz_attempt(self, attempt_id: str, fields: dict) -> None:
        await self._ensure_db()
        await self.db.quiz_attempts.update_one({"attempt_id": attempt_id}, {"$set": fields})

    async def get_quiz_attempts(self, user_id: str, limit: int = 60) -> list[dict]:
        await self._ensure_db()
        cursor = self.db.quiz_attempts.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def _ensure_db(self) -> None:
        """Make sure there is a connection, reconnecting if MongoDB came back.

        The backend used to connect once at startup only: if MongoDB was down
        then, every request failed until the backend itself was restarted, even
        after MongoDB was running again. Now a request that finds no connection
        tries to reconnect (at most every RECONNECT_INTERVAL_SECONDS). Once
        connected, the Mongo driver itself rides out later outages.
        """
        if self.enabled and self.db is not None:
            return
        if self._connect_lock is None:
            self._connect_lock = asyncio.Lock()
        async with self._connect_lock:
            if self.enabled and self.db is not None:
                return  # another request reconnected while this one waited
            if time.monotonic() - self._last_attempt >= RECONNECT_INTERVAL_SECONDS:
                logger.info("MongoDB not connected; trying to reconnect")
                await self.connect()
        if not self.enabled or self.db is None:
            raise DatabaseUnavailable("MongoDB is not connected")

    async def is_healthy(self, timeout: float = 2.0) -> bool:
        """A real check for /health: reconnect if needed, then ping."""
        try:
            await asyncio.wait_for(self._ensure_db(), timeout=timeout + 6)
            await asyncio.wait_for(self.client.admin.command("ping"), timeout=timeout)
            return True
        except Exception:
            return False


database = DatabaseManager()
