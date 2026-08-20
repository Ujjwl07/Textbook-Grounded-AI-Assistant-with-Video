import os
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger("textbook_rag.chunk_logger")


class ExtractedChunk(BaseModel):
    """Data transfer object representing a textbook chunk retrieved from the database."""
    chunk_id: Optional[str] = None
    score: float = Field(default=0.0, description="Similarity score from vector search")
    content: str = Field(..., description="The main text content of the chunk")
    pdf_name: Optional[str] = None
    class_level: Optional[str] = None
    subject: Optional[str] = None
    part: Optional[str] = None
    chapter_number: Optional[Union[int, str]] = None
    chapter_name: Optional[str] = None
    section: Optional[str] = None
    chunk_type: Optional[str] = "text"
    previous_text: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_qdrant_point(cls, point: Any) -> "ExtractedChunk":
        """Convert a Qdrant ScoredPoint / Record into an ExtractedChunk."""
        payload = getattr(point, "payload", {}) or {}
        score = getattr(point, "score", 0.0) or 0.0
        chunk_id = str(getattr(point, "id", ""))
        
        return cls(
            chunk_id=chunk_id,
            score=score,
            content=payload.get("content", ""),
            pdf_name=payload.get("pdf_name"),
            class_level=str(payload.get("class_level", "")),
            subject=payload.get("subject"),
            part=payload.get("part"),
            chapter_number=payload.get("chapter_number"),
            chapter_name=payload.get("chapter_name"),
            section=payload.get("section"),
            chunk_type=payload.get("chunk_type", "text"),
            previous_text=payload.get("previous_text"),
            metadata=payload,
        )


class ChunkLogger:
    """Handles logging and file persistence of chunks extracted from the database during RAG queries."""

    def __init__(self, log_file_path: Optional[Path] = None):
        settings = get_settings()
        self.log_file_path = log_file_path or settings.chunks_log_path
        self._ensure_log_directory()
        self._setup_file_logger()

    def _ensure_log_directory(self) -> None:
        """Create output and logs directories if they do not exist."""
        self.log_file_path.parent.mkdir(parents=True, exist_ok=True)

    def _setup_file_logger(self) -> None:
        """Configure standard logger handler for chunk logger."""
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
            logger.setLevel(logging.INFO)

    def log_retrieved_chunks(
        self,
        query: str,
        chunks: List[Union[ExtractedChunk, Dict[str, Any]]],
        filters: Optional[Dict[str, Any]] = None,
        caller: Optional[str] = None,
    ) -> str:
        """
        Logs and writes extracted textbook chunks to the dedicated log file.
        
        Args:
            query: The user question or search topic.
            chunks: List of retrieved chunks (either ExtractedChunk objects or dicts).
            filters: Optional metadata filters applied (subject, class_level, etc.).
            caller: Optional identifier of the calling service or module.
            
        Returns:
            The formatted log block string that was written to file.
        """
        self._ensure_log_directory()
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
        
        # Convert any dicts to ExtractedChunk
        normalized_chunks: List[ExtractedChunk] = []
        for c in chunks:
            if isinstance(c, ExtractedChunk):
                normalized_chunks.append(c)
            elif isinstance(c, dict):
                normalized_chunks.append(ExtractedChunk(**c))
            elif hasattr(c, "payload"):
                normalized_chunks.append(ExtractedChunk.from_qdrant_point(c))

        total_chunks = len(normalized_chunks)
        scores = [c.score for c in normalized_chunks if c.score is not None]
        top_score = max(scores) if scores else 0.0
        low_score = min(scores) if scores else 0.0

        filter_desc = ", ".join(f"{k}={v}" for k, v in (filters or {}).items() if v is not None) or "None"
        caller_desc = f" (Caller: {caller})" if caller else ""

        # Build readable structured block
        lines = [
            "=" * 80,
            f"[{timestamp}] DATABASE CHUNK EXTRACTION EVENT{caller_desc}",
            f"QUESTION / QUERY : \"{query}\"",
            f"FILTERS APPLIED  : {filter_desc}",
            f"CHUNKS EXTRACTED : {total_chunks} chunk(s) (Score range: {low_score:.4f} to {top_score:.4f})",
            "-" * 80,
        ]

        if not normalized_chunks:
            lines.append(">>> NO CHUNKS MATCHED THE QUERY IN DATABASE <<<")
        else:
            for idx, chunk in enumerate(normalized_chunks, start=1):
                ch_info = f"Chapter {chunk.chapter_number}: {chunk.chapter_name}" if chunk.chapter_name else f"Chapter {chunk.chapter_number or 'N/A'}"
                src_info = f"Class {chunk.class_level or 'N/A'} {chunk.subject or 'N/A'} {f'({chunk.part})' if chunk.part else ''} - {ch_info}"
                
                lines.append(f"--- [CHUNK #{idx}] Score: {chunk.score:.4f} | ID: {chunk.chunk_id or 'N/A'} ---")
                lines.append(f"Source   : {src_info}")
                lines.append(f"Section  : {chunk.section or 'N/A'} | Type: {chunk.chunk_type or 'text'} | PDF: {chunk.pdf_name or 'N/A'}")
                
                if chunk.previous_text:
                    prev_snippet = chunk.previous_text.strip().replace("\n", " ")
                    if len(prev_snippet) > 200:
                        prev_snippet = "..." + prev_snippet[-200:]
                    lines.append(f"Pre-Context: {prev_snippet}")

                lines.append("Content  :")
                # Indent content for clean readability
                for line in chunk.content.strip().splitlines():
                    lines.append(f"  {line}")
                lines.append("")

        lines.append("=" * 80)
        lines.append("\n")

        formatted_block = "\n".join(lines)

        # Write to separate log file
        try:
            with open(self.log_file_path, "a", encoding="utf-8") as f:
                f.write(formatted_block)
        except Exception as err:
            logger.error(f"Failed to write chunks to log file {self.log_file_path}: {err}")

        # Also emit standard logger message for terminal / log aggregation
        logger.info(
            f"Extracted {total_chunks} chunk(s) from database for query: '{query}' | "
            f"Top score: {top_score:.4f} | Written to: {self.log_file_path}"
        )

        return formatted_block

    def get_recent_log_content(self, max_bytes: int = 32768) -> str:
        """Read recent content from the chunks log file."""
        if not self.log_file_path.exists():
            return "No chunk extraction log recorded yet."
        try:
            size = self.log_file_path.stat().st_size
            offset = max(0, size - max_bytes)
            with open(self.log_file_path, "r", encoding="utf-8", errors="replace") as f:
                if offset > 0:
                    f.seek(offset)
                    # Discard partial line
                    f.readline()
                return f.read()
        except Exception as err:
            return f"Error reading log file: {err}"


chunk_logger = ChunkLogger()
