import logging
from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class DatabaseManager:
    """Manage MongoDB database operations for persistence."""
    
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.enabled = False

    async def connect(self) -> None:
        try:
            self.client = AsyncIOMotorClient(self.settings.mongodb_uri, serverSelectionTimeoutMS=5000)
            await self.client.admin.command("ping")
            self.db = self.client[self.settings.mongodb_db_name]
            
            await self.db.users.create_index("email", unique=True)
            await self.db.videos.create_index("job_id", unique=True)
            await self.db.videos.create_index([("user_id", 1), ("created_at", -1)])
            await self.db.quiz_questions.create_index("question_id", unique=True)
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
        self._require_db()
        user = await self.db.users.find_one({"email": email.lower().strip()}, {"_id": 0})
        if user:
            user["is_admin"] = await self.is_user_admin(user["email"])
        return user

    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        self._require_db()
        user = await self.db.users.find_one({"id": user_id}, {"_id": 0})
        if user:
            user["is_admin"] = await self.is_user_admin(user["email"])
        return user

    async def setup_admin_seed(self) -> None:
        count = await self.db.admins.count_documents({})
        if count == 0:
            await self.db.admins.insert_one({"email": "admin@admin.com", "created_at": datetime.utcnow()})

    async def is_user_admin(self, email: str) -> bool:
        self._require_db()
        admin = await self.db.admins.find_one({"email": email.lower().strip()})
        return bool(admin)

    async def add_admin(self, email: str) -> None:
        self._require_db()
        await self.db.admins.update_one(
            {"email": email.lower().strip()},
            {"$set": {"email": email.lower().strip(), "created_at": datetime.utcnow()}},
            upsert=True
        )

    async def create_user(self, user: dict) -> None:
        self._require_db()
        await self.db.users.insert_one(user)

    async def update_user(self, user_id: str, updates: dict) -> None:
        self._require_db()
        await self.db.users.update_one(
            {"id": user_id},
            {"$set": {**updates, "updated_at": datetime.utcnow()}},
        )

    async def save_video_record(self, record: dict) -> None:
        self._require_db()
        await self.db.videos.update_one(
            {"job_id": record["job_id"]},
            {"$set": {**record, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    async def get_video_record(self, job_id: str) -> Optional[dict]:
        self._require_db()
        return await self.db.videos.find_one({"job_id": job_id}, {"_id": 0})

    async def list_user_videos(self, user_id: str, limit: int = 20) -> list[dict]:
        self._require_db()
        cursor = self.db.videos.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    async def get_video_by_filename(self, filename: str) -> Optional[dict]:
        self._require_db()
        return await self.db.videos.find_one({"local_filename": filename}, {"_id": 0})

    async def get_quiz_question(self, question_id: str) -> Optional[dict]:
        self._require_db()
        return await self.db.quiz_questions.find_one({"question_id": question_id}, {"_id": 0})

    async def upsert_quiz_question(self, question: dict) -> None:
        self._require_db()
        await self.db.quiz_questions.update_one(
            {"question_id": question["question_id"]},
            {"$set": {**question, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    async def save_quiz_attempt(self, attempt: dict) -> None:
        self._require_db()
        await self.db.quiz_attempts.insert_one({**attempt, "created_at": datetime.utcnow()})

    async def get_quiz_attempts(self, user_id: str, limit: int = 20) -> list[dict]:
        self._require_db()
        cursor = self.db.quiz_attempts.find({"user_id": user_id}, {"_id": 0}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    def _require_db(self) -> None:
        if not self.enabled or self.db is None:
            raise RuntimeError("MongoDB is not connected")


database = DatabaseManager()
