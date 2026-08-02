from datetime import datetime
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient

from app.core.config import get_settings


class CacheManager:
    def __init__(self) -> None:
        self.settings = get_settings()
        self.client: Optional[AsyncIOMotorClient] = None
        self.db = None
        self.enabled = False

    async def connect(self) -> None:
        try:
            self.client = AsyncIOMotorClient(self.settings.mongodb_uri, serverSelectionTimeoutMS=1500)
            await self.client.admin.command("ping")
            self.db = self.client[self.settings.mongodb_db_name]
            await self.db.video_cache.create_index("cache_key", unique=True)
            await self.db.video_cache.create_index("created_at", expireAfterSeconds=self.settings.cache_ttl_seconds)
            await self.db.students.create_index("student_id", unique=True)
            await self.db.users.create_index("email", unique=True)
            await self.db.videos.create_index("job_id", unique=True)
            await self.db.quiz_attempts.create_index([("student_id", 1), ("created_at", -1)])
            self.enabled = True
        except Exception as exc:
            self.enabled = False
            raise RuntimeError(f"MongoDB connection failed: {exc}") from exc

    async def close(self) -> None:
        if self.client:
            self.client.close()

    @staticmethod
    def build_cache_key(topic: str, subject: Optional[str], class_level: Optional[str]) -> str:
        parts = [subject or "generic", class_level or "all", topic]
        return "::".join(part.strip().lower().replace(" ", "-") for part in parts)

    async def get_cached_video(self, cache_key: str) -> Optional[dict]:
        self._require_db()
        return await self.db.video_cache.find_one({"cache_key": cache_key}, {"_id": 0})

    async def save_cached_video(self, cache_key: str, payload: dict) -> None:
        self._require_db()
        await self.db.video_cache.update_one(
            {"cache_key": cache_key},
            {"$set": {**payload, "cache_key": cache_key, "created_at": datetime.utcnow()}},
            upsert=True,
        )

    async def get_student(self, student_id: str) -> Optional[dict]:
        self._require_db()
        return await self.db.students.find_one({"student_id": student_id}, {"_id": 0})

    async def save_student(self, profile: dict) -> None:
        self._require_db()
        await self.db.students.update_one(
            {"student_id": profile["student_id"]},
            {"$set": {**profile, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    async def get_user_by_email(self, email: str) -> Optional[dict]:
        self._require_db()
        return await self.db.users.find_one({"email": email.lower().strip()}, {"_id": 0})

    async def get_user_by_id(self, user_id: str) -> Optional[dict]:
        self._require_db()
        return await self.db.users.find_one({"id": user_id}, {"_id": 0})

    async def create_user(self, user: dict) -> None:
        self._require_db()
        await self.db.users.insert_one(user)

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

    async def save_quiz_attempt(self, attempt: dict) -> None:
        self._require_db()
        await self.db.quiz_attempts.insert_one({**attempt, "created_at": datetime.utcnow()})

    async def get_quiz_attempts(self, student_id: str, limit: int = 20) -> list[dict]:
        self._require_db()
        cursor = self.db.quiz_attempts.find({"student_id": student_id}, {"_id": 0}).sort("created_at", -1).limit(limit)
        return await cursor.to_list(length=limit)

    def _require_db(self) -> None:
        if not self.enabled or self.db is None:
            raise RuntimeError("MongoDB is not connected")


cache_manager = CacheManager()
