from typing import Optional
from rag_llm_module.domain.interfaces.cache_provider import ICacheProvider
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("infrastructure.cache.redis")


class RedisCacheProvider(ICacheProvider):
    """Redis implementation of ICacheProvider."""

    def __init__(self, redis_url: str = "redis://localhost:6379/0"):
        self.redis_url = redis_url
        self._client = None

    async def _get_client(self):
        if self._client is None:
            try:
                import redis.asyncio as aioredis
                self._client = aioredis.from_url(self.redis_url, decode_responses=True)
            except ImportError:
                logger.warning("redis package not installed. Install redis-py to use RedisCacheProvider.")
                raise RuntimeError("redis package is required for RedisCacheProvider.")
        return self._client

    async def get(self, key: str) -> Optional[str]:
        try:
            client = await self._get_client()
            return await client.get(key)
        except Exception as e:
            logger.error(f"Redis GET failed for key '{key}': {e}")
            return None

    async def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> None:
        try:
            client = await self._get_client()
            if ttl_seconds:
                await client.setex(key, ttl_seconds, value)
            else:
                await client.set(key, value)
        except Exception as e:
            logger.error(f"Redis SET failed for key '{key}': {e}")

    async def delete(self, key: str) -> None:
        try:
            client = await self._get_client()
            await client.delete(key)
        except Exception as e:
            logger.error(f"Redis DELETE failed for key '{key}': {e}")
