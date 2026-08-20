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
class ChunkSearchResult:
    """Chunks plus the filters that produced them, for logging and evaluation.

    Distinct from ``RetrievalResult`` below, which is the API-facing model:
    this one is the raw output of a single vector search.
    """

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
        chapter_number: Optional[object] = None,
        pdf_name: Optional[str] = None,
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

        if chapter_number not in (None, ""):
            conditions.append(
                FieldCondition(key="chapter_number", match=MatchValue(value=chapter_number))
            )

        if pdf_name:
            conditions.append(
                FieldCondition(key="pdf_name", match=MatchAny(any=_case_variants(pdf_name)))
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
        chapter_number: Optional[object] = None,
        pdf_name: Optional[str] = None,
        include_out_of_scope: bool = False,
        score_threshold: Optional[float] = None,
    ) -> ChunkSearchResult:
        """Embed ``query`` and return the top matching in-scope chunks."""
        if not query or not query.strip():
            return ChunkSearchResult(query=query, chunks=[], applied_filters={})

        query_filter = self.build_filter(
            subject=subject,
            class_level=class_level,
            chunk_types=chunk_types,
            chapter_name=chapter_name,
            chapter_number=chapter_number,
            pdf_name=pdf_name,
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
            "chapter_number": chapter_number,
            "pdf_name": pdf_name,
            "top_k": top_k,
        }
        logger.debug("Retrieved %s chunks for %r with %s", len(chunks), query, applied)
        return ChunkSearchResult(query=query, chunks=chunks, applied_filters=applied)

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

    def find_topic_scope(
        self,
        topic: str,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
        top_k: int = 8,
        override_margin: float = 0.10,
    ) -> Optional[dict]:
        """Resolve which book and chapter a topic belongs to.

        Callers may know none, some or all of subject and class. Anything not
        supplied is inferred from the corpus rather than defaulted, because a
        silent default is worse than a search: defaulting an unspecified subject
        to Physics routed "Photosynthesis" to the Thermodynamics chapter.

        A supplied subject is also overridden when searching without it finds a
        markedly better match, so a student who picks the wrong subject in a
        dropdown still gets the right chapter. The margin separates the two cases
        cleanly in measurement: with a correct subject the filtered and unfiltered
        top similarities differ by at most 0.003 ("Human Reproduction" 0.595 vs
        0.595, "Chemical Kinetics" 0.677 vs 0.680), while with a wrong subject the
        unfiltered search wins by 0.28 or more ("Photosynthesis" as Physics scores
        0.305 against 0.728 unfiltered).

        Returns ``{chapter, subject, class_level, score, top_score, inferred}``
        or None.
        """
        from collections import defaultdict

        def best(subject_filter):
            chunks = self.search(
                topic, subject=subject_filter, class_level=class_level, top_k=top_k
            ).chunks
            if not chunks:
                return None
            weights = defaultdict(float)
            for chunk in chunks:
                if chunk.chapter_name:
                    weights[(chunk.chapter_name, chunk.subject, chunk.class_level)] += chunk.score
            if not weights:
                return None
            (chapter, found_subject, found_class), score = max(
                weights.items(), key=lambda kv: kv[1]
            )
            return {
                "chapter": chapter,
                "subject": found_subject or subject_filter,
                "class_level": found_class or class_level,
                "score": score,
                # Ranking uses the best single chunk, not the accumulated weight:
                # the sum grows with how many chunks a chapter contributed, which
                # is not a measure of how well the topic matched.
                "top_score": max(c.score for c in chunks),
            }

        result = best(subject)
        inferred = []

        if subject:
            relaxed = best(None)
            if relaxed and (
                result is None
                or relaxed["top_score"] > result["top_score"] + override_margin
            ):
                if result is not None:
                    logger.info(
                        "Topic %r was given subject %r but matches %s far better "
                        "(%.3f vs %.3f); using the corpus match",
                        topic, subject, relaxed["subject"],
                        relaxed["top_score"], result["top_score"],
                    )
                inferred.append("subject")
                result = relaxed
        else:
            inferred.append("subject")

        if result is None:
            return None

        if not class_level:
            inferred.append("class_level")

        result["inferred"] = sorted(set(inferred))
        logger.info(
            "Topic %r resolved to Class %s %s / %s (inferred: %s)",
            topic, result["class_level"], result["subject"],
            result["chapter"], result["inferred"] or "nothing",
        )
        return result

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

# Abbreviations whose full stop is not a sentence end. Without these, "the
# geometry is shown in Fig. 9.3" split into "... shown in Fig." and "9.3 ...",
# and the first half reached a slide as a sentence ending in "Fig.". The
# lookbehinds have to include the dot: at the split point the preceding
# characters are "Fig.", not "Fig".
_ABBREVIATIONS = ("Fig", "Figs", "Eq", "Eqs", "Ref", "Refs", "No", "Nos",
                  "Sec", "Ch", "Vol", "Approx", "cf", "vs", "etc")
_SENTENCE_END = re.compile(
    r"(?<=[.!?])"
    # A lone initial, as in "J. J. Thomson".
    r"(?<![A-Z]\.)"
    r"(?<!i\.e\.)(?<!e\.g\.)"
    + "".join(r"(?<!%s\.)" % abbreviation for abbreviation in _ABBREVIATIONS)
    + r"\s+"
)


# Characters that only appear when the PDF's encoding was mis-decoded: the
# angle sign in "∠i = ∠r" extracts as "Ð", the degree sign as "¢". Legitimate
# scientific symbols (° ± ² ³ µ × ÷ ∝ Δ and the Greek letters) are deliberately
# not in this set.
_MOJIBAKE = re.compile(r"[ÐÞðþ¢¤¦§¨©¬®¯´¶¸ºÿ" + "\ufffd]")

# Margin numbering that extraction pulls into the prose: "(9.33)" from a
# numbered equation, "(iv)" or "(a)" from a list item.
_LEADING_NUMBERING = re.compile(
    r"^\s*\(\s*(?:\d+(?:\.\d+)*|[ivxlcIVXLC]+|[a-zA-Z])\s*\)"
)

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


# NCERT sets its section headings with a decorative oversized first letter, and
# the PDF stores that letter as its own text run. Extraction therefore echoes the
# heading: "FERTILISATION AND IMPLANTATION IMPLANTATIONMPLANTATION" is one
# heading, not three words. The same echo appears mid-sentence around bolded key
# terms ("... is called fertilisation.fertilisation."). Left in, it reaches the
# slides verbatim and inflates the word counts split_sentences() filters on.
#
# Fixing this at the source needs the PDFs re-ingested; until then it is cleaned
# on the way out, which costs one pass over text already in memory.

# The echo takes two shapes, glued and spaced. Both length floors are set well
# above what English doubles naturally: "had had" and "that that" must survive,
# while "stable table" must not collapse to "stable".
#
# "IMPLANTATIONMPLANTATION" -> a word followed by itself minus its capital.
_ECHO_GLUED = re.compile(r"\b(\w)(\w{4,})\2\b")
# "GRAVITATION RAVITATION" -> the same, with the runs separated by a space.
_ECHO_DROPCAP = re.compile(r"\b(\w)(\w{6,})\s+\2\b")
# "WORD WORD" or "word.word" -> the word repeated whole.
_ECHO_REPEATED = re.compile(r"\b(\w{6,})\b([.\s]+)\1\b", re.I)
# Exactly two dots, which is what an echo leaves behind. A real ellipsis is
# three and stays intact.
_ECHO_DOTS = re.compile(r"(?<!\.)\.\.(?!\.)")


def collapse_echoes(text: str) -> str:
    """Remove the duplicated words left behind by drop-cap extraction."""
    for _ in range(3):
        collapsed = _ECHO_GLUED.sub(r"\1\2", text)
        collapsed = _ECHO_DROPCAP.sub(r"\1\2", collapsed)
        collapsed = _ECHO_REPEATED.sub(r"\1", collapsed)
        if collapsed == text:
            break
        text = collapsed
    return _ECHO_DOTS.sub(".", text)


def clean_ncert_text(text: str) -> str:
    """Strip markdown and print artefacts from extracted chunk text."""
    cleaned = str(text or "")
    for pattern in _NOISE_PATTERNS:
        cleaned = pattern.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return collapse_echoes(cleaned.strip())


def split_sentences(text: str) -> list:
    """Split cleaned text into sentences, dropping fragments and stray headers."""
    sentences = []
    for raw in _SENTENCE_END.split(clean_ncert_text(text)):
        # Markdown emphasis survives clean_ncert_text, which only strips runs
        # of two or more underscores. A single one wrapping a sentence —
        # "_Can you name some other parts ... may occur?_." — left the checks
        # below looking at "_" instead of at the first and last real character.
        sentence = raw.strip(" -–—•|_*")
        if len(sentence.split()) < 6:
            continue
        # Table rows and figure labels are not narratable prose.
        # "Fig\b" does not match "Figure": the word boundary after "Fig"
        # fails against the following "u", so full-word captions ("Figure
        # 2.1(b) Diagrammatic view of male reproductive system") reached the
        # slides as if they were prose.
        if sentence.count("|") > 1 or re.match(
            r"^(Figs?\.?|Figures?|Tables?|Examples?)\b", sentence, re.I
        ):
            continue
        # Section headers swept up by the splitter, e.g. "6.7 Chemical The
        # reactions of haloalkanes may be divided into the following categories".
        if re.match(r"^\d+(\.\d+)*\s", sentence):
            continue
        # Equation and list numbering carried in from the margin: "(9.33) Such a
        # system of combination of lenses ..." and "(iv) The ray incident at any
        # angle at the pole." Both reached slides verbatim, numbering and all.
        if _LEADING_NUMBERING.match(sentence):
            continue
        # Rhetorical questions the textbook asks its reader — "Can you name some
        # other parts where you think photosynthesis may occur?" A bullet that
        # asks a question the video never answers reads as a mistake.
        #
        # Trailing punctuation has to come off first. Ingestion appends a full
        # stop to any line that does not end in one, and re-joining leaves
        # "... may occur?." — which endswith("?") does not catch, so the
        # question reached a slide anyway.
        if sentence.rstrip(" .;:,_*").endswith("?"):
            continue
        # A fragment the splitter cut mid-sentence: real prose opens with a
        # capital, a digit or a quote. "important features of the Quantum
        # mechanical model of atom." is the tail of a sentence, not one.
        if sentence[:1].islower():
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
        # Mis-decoded characters: the sentence is readable enough to score well
        # on similarity but renders as "Ð i = Ð r ¢" on the slide.
        if _MOJIBAKE.search(sentence):
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


# ---------------------------------------------------------------------------
# API surface: chunk logging and LLM-facing context
# ---------------------------------------------------------------------------
#
# Two retrievers were written against this collection independently. This module
# keeps the NEET-scoped one — metadata filters, corpus-inferred subject/class,
# sentence-window re-ranking — and exposes it through the API the rest of the
# app calls: ``retriever.retrieve()`` returning a ``RetrievalResult``, with every
# hit written to the dedicated chunks log.
#
# The split is deliberate. ``NCERTRetriever`` owns retrieval quality and knows
# nothing about logging or the API; ``TextbookRetriever`` owns the contract that
# query.py, job_queue.py and scripts/ask_question.py depend on.

from typing import Any, Dict, List, Union  # noqa: E402

from pydantic import BaseModel, Field  # noqa: E402

from app.utils.chunk_logger import ExtractedChunk, chunk_logger  # noqa: E402


class RetrievalResult(BaseModel):
    """One retrieval call, as the API and the LLM stage consume it."""

    query: str
    chunks: List[ExtractedChunk] = Field(default_factory=list)
    context_text: str = Field(default="", description="Assembled context formatted for LLM prompts")
    answer: Optional[str] = Field(default=None, description="Grounded answer generated by the LLM")
    total_chunks: int = 0
    top_score: float = 0.0
    filters_applied: Dict[str, Any] = Field(default_factory=dict)
    log_file_path: str = ""


def _to_extracted(chunk: RetrievedChunk) -> ExtractedChunk:
    """Flatten an internal hit into the DTO the logger and API share."""
    return ExtractedChunk(
        chunk_id=str(chunk.chunk_id) if chunk.chunk_id not in ("", None) else None,
        score=chunk.score,
        content=chunk.content,
        pdf_name=chunk.pdf_name or None,
        class_level=chunk.class_level or None,
        subject=chunk.subject or None,
        chapter_number=chunk.chapter_number if chunk.chapter_number != "" else None,
        chapter_name=chunk.chapter_name or None,
        section=chunk.section or None,
        chunk_type=chunk.chunk_type or "text",
        previous_text=chunk.previous_text or None,
    )


class TextbookRetriever:
    """Logged, LLM-facing retrieval over the NCERT collection."""

    def __init__(self, retriever: Optional[NCERTRetriever] = None, logger_=None):
        self._retriever = retriever
        self._chunk_logger = logger_ or chunk_logger

    @property
    def retriever(self) -> NCERTRetriever:
        # Resolved lazily so importing this module does not load a 90 MB model.
        if self._retriever is None:
            self._retriever = get_retriever()
        return self._retriever

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        subject: Optional[str] = None,
        class_level: Optional[Union[str, int]] = None,
        chapter_number: Optional[Union[str, int]] = None,
        pdf_name: Optional[str] = None,
        score_threshold: Optional[float] = None,
        caller: Optional[str] = None,
        log_to_file: bool = True,
    ) -> RetrievalResult:
        """Retrieve in-scope chunks for ``query`` and log every hit.

        Subject and class are resolved against the corpus before searching, so a
        caller that supplies neither — or supplies the wrong subject — still gets
        the right chapter. The resolved scope is returned in ``filters_applied``
        because the scene and narration stages need it: without it a Biology
        lesson whose subject was inferred is read in the Physics voice.
        """
        scope = None
        try:
            scope = self.retriever.find_topic_scope(
                query, subject=subject, class_level=class_level
            )
        except Exception as exc:
            logger.warning("Topic scope resolution failed for %r: %s", query, exc)

        resolved_subject = (scope or {}).get("subject") or subject
        resolved_class = (scope or {}).get("class_level") or class_level
        chapter_name = (scope or {}).get("chapter")

        search = self.retriever.search(
            query,
            subject=resolved_subject,
            class_level=resolved_class,
            top_k=top_k,
            chapter_name=chapter_name,
            chapter_number=chapter_number,
            pdf_name=pdf_name,
            score_threshold=score_threshold,
        )

        chunks = [_to_extracted(chunk) for chunk in search.chunks]
        context_text = self.retriever.build_context(search.chunks)

        filters_applied = dict(search.applied_filters)
        filters_applied.update({
            "requested_subject": subject,
            "requested_class_level": class_level,
            "resolved_subject": resolved_subject,
            "resolved_class_level": resolved_class,
            "inferred": (scope or {}).get("inferred", []),
        })

        log_file_path = ""
        if log_to_file:
            try:
                self._chunk_logger.log_retrieved_chunks(
                    query=query, chunks=chunks, filters=filters_applied, caller=caller
                )
                log_file_path = str(getattr(self._chunk_logger, "log_file_path", ""))
            except Exception as exc:
                # Logging is observability, not the job: a failed write must not
                # take down a generation that already has its context.
                logger.warning("Chunk logging failed for %r: %s", query, exc)

        return RetrievalResult(
            query=query,
            chunks=chunks,
            context_text=context_text,
            total_chunks=len(chunks),
            top_score=max((c.score for c in chunks), default=0.0),
            filters_applied=filters_applied,
            log_file_path=log_file_path,
        )


retriever = TextbookRetriever()
