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
import re
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

    # -- sentence-window retrieval ----------------------------------------

    def search_passages(
        self,
        query: str,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        top_k_chunks: int = 6,
        top_k_passages: int = 6,
        window: int = 2,
        cue_set: Optional[list] = None,
        chapter_name: Optional[str] = None,
        min_words: int = 8,
    ) -> list:
        """Return precise passages from inside the retrieved chunks.

        Retrieves ``top_k_chunks`` whole chunks, splits them into sentences,
        forms overlapping windows of ``window`` sentences, embeds every window
        and re-ranks against the query. ``cue_set`` optionally biases the ranking
        toward definitional or cautionary phrasing.
        """
        chunks = self.search(
            query,
            subject=subject,
            class_level=class_level,
            top_k=top_k_chunks,
            chapter_name=chapter_name,
        ).chunks
        if not chunks:
            return []

        candidates = []   # (text, chunk)
        for chunk in chunks:
            sentences = split_sentences(chunk.content)
            for index in range(len(sentences)):
                text = " ".join(sentences[index:index + window]).strip()
                if len(text.split()) < min_words:
                    continue
                candidates.append((text, chunk))

        if not candidates:
            return []

        # Deduplicate identical windows, keeping the first source chunk.
        seen, unique = set(), []
        for text, chunk in candidates:
            key = text[:120].lower()
            if key in seen:
                continue
            seen.add(key)
            unique.append((text, chunk))

        query_vector = self.model.encode(query, normalize_embeddings=True)
        passage_vectors = self.model.encode(
            [text for text, _ in unique], normalize_embeddings=True, batch_size=64
        )

        scored = []
        for (text, chunk), vector in zip(unique, passage_vectors):
            similarity = float(vector @ query_vector)
            if cue_set:
                similarity += _cue_bonus(text, cue_set)
            scored.append(RetrievedPassage(
                text=text,
                score=similarity,
                citation=chunk.citation,
                chapter_name=chunk.chapter_name,
                subject=chunk.subject,
                class_level=chunk.class_level,
                chunk_id=chunk.chunk_id,
            ))

        scored.sort(key=lambda p: -p.score)
        return scored[:top_k_passages]

    def find_chapter(
        self,
        topic: str,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        top_k: int = 8,
    ) -> Optional[str]:
        """Pick the chapter a topic belongs to, by score-weighted vote.

        This is the first stage of a two-stage search. Without it, a passage
        search for "Gravitation" returned "Every object on the earth experiences
        the force of gravity" from Ch.4 Laws of Motion — topically related, but
        not the chapter being taught.
        """
        from collections import defaultdict

        chunks = self.search(topic, subject=subject, class_level=class_level, top_k=top_k).chunks
        if not chunks:
            return None
        weights = defaultdict(float)
        for chunk in chunks:
            if chunk.chapter_name:
                weights[chunk.chapter_name] += chunk.score
        return max(weights, key=weights.get) if weights else None

    def find_definition(
        self,
        topic: str,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        chapter_name: Optional[str] = None,
    ) -> Optional[RetrievedPassage]:
        """Best definitional passage for ``topic``, or None if nothing qualifies.

        Two things make this work where a plain vector search does not:

        1. The search is scoped to the topic's own chapter (see find_chapter),
           because the defining sentence often does not contain the topic word at
           all — "Every body in the universe attracts every other body ..." never
           says "gravitation", so it loses on similarity to weaker sentences that
           do repeat the word.
        2. Definitional phrasing is rewarded via _DEFINITION_CUES, and a minimum
           length is enforced so summary fragments like "Photosynthesis has two
           stages." cannot win over the actual definition.
        """
        if chapter_name is None:
            chapter_name = self.find_chapter(topic, subject=subject, class_level=class_level)

        query = f"{topic} is defined as: statement of the definition of {topic}"
        passages = self.search_passages(
            query,
            subject=subject,
            class_level=class_level,
            chapter_name=chapter_name,
            top_k_chunks=12,
            top_k_passages=5,
            window=1,
            cue_set=_DEFINITION_CUES,
            min_words=14,
        )
        # Quality bar: only return a passage that actually reads as a definition.
        # Similarity alone will happily surface a section header or an equation
        # caption, and a wrong "definition" on a slide is worse than none.
        for passage in passages:
            if _cue_bonus(passage.text, _DEFINITION_CUES) > 0:
                return passage
        return None

    def find_cautions(
        self,
        topic: str,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        limit: int = 3,
    ) -> list:
        """Passages that read as exceptions or cautions, for the NEET-alert scene."""
        query = (f"common mistakes exceptions and cautions about {topic}; "
                 f"note that, however, do not confuse")
        return self.search_passages(
            query,
            subject=subject,
            class_level=class_level,
            top_k_chunks=8,
            top_k_passages=limit,
            window=1,
            cue_set=_CAUTION_CUES,
        )

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


# ---------------------------------------------------------------------------
# Sentence-window retrieval
# ---------------------------------------------------------------------------

# Ingested chunks are up to ~5,000 characters (median 4,276 for a chapter), so a
# chunk embedding averages an entire section. Measured consequence: the universal
# law of gravitation sits at character 2,951 of chunk 11, and a query quoting the
# law almost verbatim did not retrieve that chunk in its top 3 at all.
#
# Re-chunking the corpus is the real fix but needs the source PDFs re-ingested.
# In the meantime, retrieving whole chunks and then re-ranking their *sentences*
# against the same query recovers the precise passage from inside the blob.

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Chapter-opening learning-objective lists, which extract badly from two-column
# pages and are never usable as narration.
_OBJECTIVE_NOISE = re.compile(
    r"(you will be able to|after studying this (unit|chapter)|objectives?\s*:)", re.I
)

# Markdown and print artefacts that survive PDF extraction.
_NOISE_PATTERNS = [
    re.compile(r"Reprint\s*\d{4}-\d{2}", re.I),
    # Header hashes anywhere, not only at a line start: extraction leaves them
    # mid-stream ("... reaction. ### 3.1 Rate of a Chemical Reaction ."), and a
    # line-anchored pattern let those through to the slides.
    re.compile(r"#+"),
    re.compile(r"\*+"),
    re.compile(r"_{2,}"),
    re.compile(r"<[^>]{1,20}>"),
]

# Sentences that read like a definition are what a CONCEPT slide needs, and
# similarity alone does not distinguish them from surrounding prose.
_DEFINITION_CUES = [
    (re.compile(r"\bis defined as\b", re.I), 0.22),
    (re.compile(r"\bis called\b", re.I), 0.16),
    (re.compile(r"\bis known as\b", re.I), 0.16),
    (re.compile(r"\bstates that\b", re.I), 0.20),
    (re.compile(r"\bis the process\b", re.I), 0.20),
    (re.compile(r"\bis a process\b", re.I), 0.18),
    (re.compile(r"\brefers to\b", re.I), 0.14),
    (re.compile(r"\bis the (?:measure|ratio|rate|amount) of\b", re.I), 0.16),
    (re.compile(r"^\s*every\b", re.I), 0.18),
    (re.compile(r"\bwe define\b", re.I), 0.18),
    # "X is the study of ...", "X is a process in which ..." — the plain copula
    # definition. Without these, NCERT's own wording was rejected: "Chemical
    # kinetics is the study of chemical reactions with respect to reaction
    # rates ..." scored 0.856 and still failed the cue check.
    (re.compile(r"\bis the (?:study|branch|science|phenomenon|tendency) of\b", re.I), 0.22),
    (re.compile(r"\bis a (?:process|phenomenon|measure|property|form) (?:of|in which|by which)\b", re.I), 0.20),
    # Topic-initial copula: a short subject followed by "is a/an/the".
    (re.compile(r"^\s*[A-Z][\w\s'’\-]{2,40}\s+(?:is|are)\s+(?:a|an|the)\b"), 0.14),
]

# Cues for the NEET-alert scene: exceptions and cautions.
_CAUTION_CUES = [
    (re.compile(r"\bhowever\b", re.I), 0.14),
    (re.compile(r"\bnote that\b", re.I), 0.18),
    (re.compile(r"\bexcept\b", re.I), 0.16),
    (re.compile(r"\bexception\b", re.I), 0.20),
    (re.compile(r"\bshould not\b", re.I), 0.16),
    (re.compile(r"\bdo not confuse\b", re.I), 0.24),
    (re.compile(r"\bremember\b", re.I), 0.14),
    (re.compile(r"\bunlike\b", re.I), 0.14),
]


def clean_ncert_text(text: str) -> str:
    """Strip markdown and print artefacts from extracted chunk text."""
    cleaned = str(text or "")
    for pattern in _NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def split_sentences(text: str) -> list:
    """Split cleaned text into sentences, dropping fragments and stray headers."""
    sentences = []
    for raw in _SENTENCE_END.split(clean_ncert_text(text)):
        sentence = raw.strip(" -–—•|")
        if len(sentence.split()) < 6:
            continue
        # Table rows and figure labels are not narratable prose.
        if sentence.count("|") > 1 or re.match(r"^(Fig|Table|Example)\b", sentence, re.I):
            continue
        # Section headers swept up by the splitter, e.g. "6.7 Chemical The
        # reactions of haloalkanes may be divided into the following categories".
        if re.match(r"^\d+(\.\d+)*\s", sentence):
            continue
        # Mostly symbols or digits: an equation line or a stray index entry.
        letters = sum(ch.isalpha() or ch.isspace() for ch in sentence)
        if letters / max(len(sentence), 1) < 0.75:
            continue
        # "After studying this Unit, you will be able to ..." objective lists.
        # On two-column NCERT pages these extract as interleaved gibberish
        # ("apply Nernst equation for calculating ... Electrochemistry is the
        # study of production of derive relation between ..."), which scores well
        # on similarity while being unreadable.
        if _OBJECTIVE_NOISE.search(sentence) or sentence.count(";") >= 2:
            continue
        sentences.append(sentence)
    return sentences


def _cue_bonus(sentence: str, cues) -> float:
    return sum(weight for pattern, weight in cues if pattern.search(sentence))


@dataclass
class RetrievedPassage:
    """One sentence-window passage taken from inside a retrieved chunk."""

    text: str
    score: float
    citation: str = ""
    chapter_name: str = ""
    subject: str = ""
    class_level: str = ""
    chunk_id: object = ""


@lru_cache(maxsize=2)
def _load_embedding_model(model_name: str):
    from sentence_transformers import SentenceTransformer

    logger.info("Loading embedding model %s", model_name)
    return SentenceTransformer(model_name)


@lru_cache(maxsize=1)
def get_retriever() -> NCERTRetriever:
    """Process-wide retriever, so the model and client load once."""
    return NCERTRetriever()
