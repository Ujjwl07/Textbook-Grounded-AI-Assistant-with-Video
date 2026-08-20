import logging
from typing import Any, Dict, List, Optional, Union
from qdrant_client import QdrantClient
from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.core.config import get_settings
from app.utils.chunk_logger import ExtractedChunk

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

    def build_filter(
        self,
        subject: Optional[str] = None,
        class_level: Optional[Union[str, int]] = None,
        chapter_number: Optional[Union[str, int]] = None,
        pdf_name: Optional[str] = None,
    ) -> Optional[Filter]:
        """Construct Qdrant Filter conditions for textbook chunk metadata."""
        conditions = []

        if subject:
            conditions.append(
                FieldCondition(key="subject", match=MatchValue(value=subject.strip()))
            )
        if class_level is not None and str(class_level).strip() and str(class_level).lower() != "all":
            conditions.append(
                FieldCondition(key="class_level", match=MatchValue(value=str(class_level).strip()))
            )
        if chapter_number is not None and str(chapter_number).strip():
            try:
                ch_int = int(chapter_number)
                conditions.append(FieldCondition(key="chapter_number", match=MatchValue(value=ch_int)))
            except ValueError:
                conditions.append(FieldCondition(key="chapter_number", match=MatchValue(value=str(chapter_number).strip())))
        if pdf_name:
            conditions.append(
                FieldCondition(key="pdf_name", match=MatchValue(value=pdf_name.strip()))
            )

        if not conditions:
            return None
        return Filter(must=conditions)

    def search_similar(
        self,
        query_vector: List[float],
        top_k: int = 5,
        subject: Optional[str] = None,
        class_level: Optional[Union[str, int]] = None,
        chapter_number: Optional[Union[str, int]] = None,
        pdf_name: Optional[str] = None,
        score_threshold: Optional[float] = None,
    ) -> List[ExtractedChunk]:
        """
        Execute vector similarity search in Qdrant collection.
        
        Args:
            query_vector: Dense embedding vector for the question/query.
            top_k: Maximum number of chunks to return.
            subject: Optional filter by subject.
            class_level: Optional filter by class level.
            chapter_number: Optional filter by chapter number.
            pdf_name: Optional filter by source PDF stem.
            score_threshold: Optional minimum cosine similarity threshold.
            
        Returns:
            List of ExtractedChunk objects ranked by similarity.
        """
        client = self.get_client()
        query_filter = self.build_filter(
            subject=subject,
            class_level=class_level,
            chapter_number=chapter_number,
            pdf_name=pdf_name,
        )

        collection_name = self.settings.qdrant_collection or "textbook_chunks"
        
        try:
            if hasattr(client, "query_points"):
                response = client.query_points(
                    collection_name=collection_name,
                    query=query_vector,
                    query_filter=query_filter,
                    limit=top_k,
                    score_threshold=score_threshold,
                    with_payload=True,
                )
                points = getattr(response, "points", []) or []
            else:
                points = client.search(
                    collection_name=collection_name,
                    query_vector=query_vector,
                    query_filter=query_filter,
                    limit=top_k,
                    score_threshold=score_threshold,
                    with_payload=True,
                )

            chunks = [ExtractedChunk.from_qdrant_point(res) for res in points]
            return chunks
        except Exception as exc:
            logger.error(f"Error during Qdrant vector search in '{collection_name}': {exc}")
            raise

    def scroll_chunks(
        self,
        limit: int = 5,
        subject: Optional[str] = None,
        class_level: Optional[Union[str, int]] = None,
    ) -> List[ExtractedChunk]:
        """Scroll chunks from collection (useful for sampling or fallbacks)."""
        client = self.get_client()
        query_filter = self.build_filter(subject=subject, class_level=class_level)
        collection_name = self.settings.qdrant_collection or "textbook_chunks"

        try:
            results, _ = client.scroll(
                collection_name=collection_name,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
            )
            return [ExtractedChunk.from_qdrant_point(res) for res in results]
        except Exception as exc:
            logger.error(f"Error scrolling Qdrant collection '{collection_name}': {exc}")
            raise

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
