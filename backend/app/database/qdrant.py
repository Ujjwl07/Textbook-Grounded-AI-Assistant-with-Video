import logging
from typing import Any, Dict, Optional
from qdrant_client import QdrantClient

from app.core.config import get_settings

logger = logging.getLogger("textbook_rag.qdrant")


class QdrantDatabase:
    """Manages Qdrant vector database connections, queries, and chunk retrieval."""

    def __init__(self, client: Optional[QdrantClient] = None) -> None:
        self.settings = get_settings()
        self._client = client

    def get_client(self) -> QdrantClient:
        """Lazily initialize and return the QdrantClient instance."""
        if self._client is None:
            if not self.settings.qdrant_url or not self.settings.qdrant_api_key:
                error_msg = (
                    "QDRANT_URL or QDRANT_API_KEY is not configured in .env. "
                    "Cannot connect to NCERT textbook vector database."
                )
                logger.error(error_msg)
                raise ConnectionError(error_msg)

            self._client = QdrantClient(
                url=self.settings.qdrant_url,
                api_key=self.settings.qdrant_api_key,
                timeout=10.0,
            )
        return self._client

    def get_collection_info(self) -> Dict[str, Any]:
        """Get diagnostic information about the Qdrant collection."""
        client = self.get_client()
        collection_name = self.settings.qdrant_collection or "textbook_chunks"
        try:
            collections = client.get_collections().collections
            names = [c.name for c in collections]
            exists = collection_name in names
            point_count = 0
            if exists:
                info = client.get_collection(collection_name)
                point_count = getattr(info, "points_count", 0) or 0
            return {
                "collection_name": collection_name,
                "exists": exists,
                "points_count": point_count,
                "all_collections": names,
            }
        except Exception as exc:
            logger.warning(f"Could not retrieve Qdrant collection info: {exc}")
            return {"collection_name": collection_name, "exists": False, "error": str(exc)}


qdrant_db = QdrantDatabase()
