"""Metadata-filtered retrieval over the NCERT Qdrant collection.

Why this module exists
----------------------
The collection holds every ingested book in one namespace: Class 9-12, four
subject labels, and both prose and table-row chunks. An unfiltered vector search
therefore answers NEET questions with the wrong book. Measured before filtering:

    "State Newton's universal law of gravitation"
        1. Class 9 Science  (0.586)
        2. Class 9 Science  (0.498)
        3. Class 11 Physics (0.495)   <- the answer a NEET student needs

    "Explain the structure and function of DNA"
        1. Class 12 Chemistry, Biomolecules (0.587)
        2. Class 12 Chemistry, Biomolecules (0.505)
        3. Class 12 Biology                 (0.466)

Both failures are fixed by constraining the search with payload filters that the
ingestion pipeline already writes. This module owns those constraints so every
caller gets them by default rather than remembering to pass them.

Three defaults do the work:
  * only Class 11 and 12 are in scope (Class 9/10 Science is off-syllabus);
  * a subject filter, when the caller knows the subject;
  * only prose chunks, because 56% of the collection is single table rows that
    are useless as narration source material.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Iterable, Optional, Sequence

from qdrant_client import QdrantClient
from qdrant_client.models import (
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
)

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# NEET covers Class 11 and 12 only. Class 9/10 "Science" was ingested from the
# same dataset root and is excluded unless a caller explicitly opts in.
NEET_CLASSES = ("11", "12")
NEET_SUBJECTS = ("physics", "chemistry", "biology")

# Prose only by default. 'table_row' chunks are single spreadsheet rows
# ("Element: Sc | Atomic radius: 164") — retrievable but not narratable.
DEFAULT_CHUNK_TYPES = ("text",)

# Payload fields worth a Qdrant index, since every query filters on them.
INDEXED_FIELDS = ("subject", "class_level", "chunk_type", "chapter_name")


def _case_variants(value: str) -> list:
    """Payload values are stored inconsistently cased ('Physics', 'part 1').

    Rather than normalising 2,876 stored records, match any plausible casing.
    """
    value = str(value).strip()
    return list(dict.fromkeys([value, value.lower(), value.upper(), value.title()]))


@dataclass
class RetrievedChunk:
    """One retrieval hit, flattened from the Qdrant payload."""

    content: str
    score: float
    subject: str = ""
    class_level: str = ""
    chapter_number: object = ""
    chapter_name: str = ""
    section: str = ""
    chunk_type: str = ""
    previous_text: str = ""
    pdf_name: str = ""
    chunk_id: object = ""

    @classmethod
    def from_point(cls, point) -> "RetrievedChunk":
        payload = point.payload or {}
        return cls(
            content=str(payload.get("content", "")).strip(),
            score=float(point.score),
            subject=str(payload.get("subject", "")),
            class_level=str(payload.get("class_level", "")),
            chapter_number=payload.get("chapter_number", ""),
            chapter_name=str(payload.get("chapter_name", "")),
            section=str(payload.get("section", "")),
            chunk_type=str(payload.get("chunk_type", "")),
            previous_text=str(payload.get("previous_text", "")),
            pdf_name=str(payload.get("pdf_name", "")),
            chunk_id=payload.get("chunk_id", ""),
        )

    @property
    def citation(self) -> str:
        """Human-readable source, e.g. 'Class 11 Physics, Ch.7 GRAVITATION'."""
        parts = []
        if self.class_level:
            parts.append(f"Class {self.class_level}")
        if self.subject:
            parts.append(self.subject)
        head = " ".join(parts)
        if self.chapter_number not in ("", None):
            head = f"{head}, Ch.{self.chapter_number}"
        if self.chapter_name:
            head = f"{head} {self.chapter_name}"
        return head.strip(", ").strip()


@dataclass
class RetrievalResult:
    """Chunks plus the filters that produced them, for logging and evaluation."""

    query: str
    chunks: list = field(default_factory=list)
    applied_filters: dict = field(default_factory=dict)

    def __len__(self) -> int:
        return len(self.chunks)

    def __iter__(self):
        return iter(self.chunks)


class NCERTRetriever:
    """Dense retrieval over the NCERT collection with NEET-scope filters."""

    def __init__(self, client: Optional[QdrantClient] = None, model=None):
        self.settings = get_settings()
        self.collection = self.settings.qdrant_collection
        self._client = client
        self._model = model

    # -- lazy resources ----------------------------------------------------

    @property
    def client(self) -> QdrantClient:
        if self._client is None:
            if not self.settings.qdrant_url:
                raise RuntimeError("QDRANT_URL is not configured")
            self._client = QdrantClient(
                url=self.settings.qdrant_url,
                api_key=self.settings.qdrant_api_key or None,
                timeout=60,
            )
        return self._client

    @property
    def model(self):
        """The embedding model is ~90 MB, so it loads on first use, not import."""
        if self._model is None:
            self._model = _load_embedding_model(self.settings.embedding_model)
        return self._model

    # -- filtering ---------------------------------------------------------

    def build_filter(
        self,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        chunk_types: Optional[Sequence[str]] = DEFAULT_CHUNK_TYPES,
        chapter_name: Optional[str] = None,
        include_out_of_scope: bool = False,
    ) -> Optional[Filter]:
        """Assemble the payload filter for a search.

        ``include_out_of_scope=True`` drops the Class 11/12 restriction; it
        exists for corpus auditing, not for student-facing retrieval.
        """
        conditions = []

        if subject:
            conditions.append(
                FieldCondition(key="subject", match=MatchAny(any=_case_variants(subject)))
            )

        if class_level:
            conditions.append(
                FieldCondition(key="class_level", match=MatchValue(value=str(class_level)))
            )
        elif not include_out_of_scope:
            conditions.append(
                FieldCondition(key="class_level", match=MatchAny(any=list(NEET_CLASSES)))
            )

        if chunk_types:
            conditions.append(
                FieldCondition(key="chunk_type", match=MatchAny(any=list(chunk_types)))
            )

        if chapter_name:
            conditions.append(
                FieldCondition(key="chapter_name", match=MatchAny(any=_case_variants(chapter_name)))
            )

        return Filter(must=conditions) if conditions else None

    # -- search ------------------------------------------------------------

    def search(
        self,
        query: str,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        top_k: int = 8,
        chunk_types: Optional[Sequence[str]] = DEFAULT_CHUNK_TYPES,
        chapter_name: Optional[str] = None,
        include_out_of_scope: bool = False,
        score_threshold: Optional[float] = None,
    ) -> RetrievalResult:
        """Embed ``query`` and return the top matching in-scope chunks."""
        if not query or not query.strip():
            return RetrievalResult(query=query, chunks=[], applied_filters={})

        query_filter = self.build_filter(
            subject=subject,
            class_level=class_level,
            chunk_types=chunk_types,
            chapter_name=chapter_name,
            include_out_of_scope=include_out_of_scope,
        )

        vector = self.model.encode(query, normalize_embeddings=True).tolist()
        response = self.client.query_points(
            collection_name=self.collection,
            query=vector,
            limit=top_k,
            query_filter=query_filter,
            with_payload=True,
            score_threshold=score_threshold,
        )

        chunks = [RetrievedChunk.from_point(point) for point in response.points]
        applied = {
            "subject": subject,
            "class_level": class_level or (None if include_out_of_scope else list(NEET_CLASSES)),
            "chunk_types": list(chunk_types) if chunk_types else None,
            "chapter_name": chapter_name,
            "top_k": top_k,
        }
        logger.debug("Retrieved %s chunks for %r with %s", len(chunks), query, applied)
        return RetrievalResult(query=query, chunks=chunks, applied_filters=applied)

    # -- context assembly --------------------------------------------------

    def build_context(
        self,
        chunks: Iterable[RetrievedChunk],
        max_chars: int = 6000,
        include_previous: bool = False,
    ) -> str:
        """Format chunks into a cited context block for the LLM prompt.

        Each passage carries its source so the script generator can be held to
        the "every fact must come from the context" rule, and so a reviewer can
        trace a claim back to a chapter.
        """
        blocks, used = [], 0
        for index, chunk in enumerate(chunks, start=1):
            body = chunk.content
            if include_previous and chunk.previous_text:
                body = f"{chunk.previous_text.strip()}\n{body}"
            header = f"[{index}] Source: {chunk.citation}\n"
            block = header + body.strip()

            if used + len(block) > max_chars:
                # A single chunk can be longer than the whole budget. Returning
                # nothing would leave the LLM ungrounded, so truncate the first
                # passage to fit instead of dropping it.
                if not blocks:
                    room = max_chars - len(header)
                    if room > 0:
                        blocks.append(header + body.strip()[:room].rstrip() + " …")
                break

            blocks.append(block)
            used += len(block)

        return "\n\n---\n\n".join(blocks)

    # -- maintenance -------------------------------------------------------

    def ensure_payload_indexes(self) -> dict:
        """Create payload indexes for the filtered fields.

        Qdrant can filter without an index, but it degrades to a full scan.
        Creating an existing index is a no-op, so this is safe to re-run.
        """
        results = {}
        for field_name in INDEXED_FIELDS:
            try:
                self.client.create_payload_index(
                    collection_name=self.collection,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                )
                results[field_name] = "ok"
            except Exception as exc:  # already exists, or insufficient rights
                results[field_name] = f"skipped: {exc}"
        return results

    def corpus_stats(self) -> dict:
        """Count points per subject/class/chunk_type by scrolling the payloads."""
        from collections import Counter

        subjects, classes, chunk_types, in_scope = Counter(), Counter(), Counter(), 0
        offset, total = None, 0
        while True:
            points, offset = self.client.scroll(
                collection_name=self.collection,
                limit=1000,
                offset=offset,
                with_payload=True,
                with_vectors=False,
            )
            for point in points:
                payload = point.payload or {}
                total += 1
                subjects[str(payload.get("subject", "?"))] += 1
                class_level = str(payload.get("class_level", "?"))
                classes[class_level] += 1
                chunk_types[str(payload.get("chunk_type", "?"))] += 1
                if class_level in NEET_CLASSES and str(payload.get("chunk_type")) == "text":
                    in_scope += 1
            if offset is None:
                break

        return {
            "total_points": total,
            "by_subject": dict(subjects.most_common()),
            "by_class": dict(classes.most_common()),
            "by_chunk_type": dict(chunk_types.most_common()),
            "retrievable_default": in_scope,
        }


@lru_cache(maxsize=2)
def _load_embedding_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model %s", model_name)
    return SentenceTransformer(model_name)


@lru_cache(maxsize=1)
def get_retriever() -> NCERTRetriever:
    """Process-wide retriever, so the model and client load once."""
    return NCERTRetriever()
