from typing import Protocol, Optional


class ICacheProvider(Protocol):
    """Protocol interface for caching operations."""

    async def get(self, key: str) -> Optional[str]:
        """Fetch string value by key, or return None if miss."""
        ...

    async def set(self, key: str, value: str, ttl_seconds: Optional[int] = None) -> None:
        """Set key-value pair with optional TTL."""
        ...

    async def delete(self, key: str) -> None:
        """Delete cache key."""
        ...
