import time
from typing import Optional, Dict, Tuple
from rag_llm_module.domain.interfaces.cache_provider import ICacheProvider
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("infrastructure.cache.memory")


class MemoryCacheProvider(ICacheProvider):
    """In-memory key-value store with TTL support for unit testing and local development."""

    def __init__(self):
        # Stores key -> (value, expiry_timestamp)
        self._store: Dict[str, Tuple[str, Optional[float]]] = {}

    async def get(self, key: str) -> Optional[str]:
        if key not in self._store:
            return None

        val, expiry = self._store[key]
        if expiry is not None and time.time() > expiry:
            logger.debug(f"Cache key expired: {key}")
            del self._store[key]
            return None

        return val

    async def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> None:
        expiry = time.time() + ttl_seconds if ttl_seconds is not None else None
        self._store[key] = (value, expiry)
        logger.debug(f"Cache set key: {key} (ttl={ttl_seconds}s)")

    async def delete(self, key: str) -> None:
        self._store.pop(key, None)
