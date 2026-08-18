"""
Hallucination Detector Module for RAG Educational Platform.

Performs sentence-level hallucination detection between retrieved NCERT context
and LLM-generated teaching scripts. Uses cosine similarity, n-gram overlap,
and subject-aware rule-based checkers (equations, units, definitions, reactions,
biological terms) to produce a structured HallucinationReport with per-sentence
confidence scores and a final JSON report.

Architecture:
    SentenceSegmenter        -- splits text into clean sentences
    TFIDFVectorizer          -- pure-Python TF-IDF for semantic similarity
    SemanticSimilarityEngine -- sentence x context cosine similarity
    EquationChecker          -- detects wrong/ungrounded equations
    UnitChecker              -- flags incorrect or ungrounded SI units
    DefinitionChecker        -- detects ungrounded definitional claims
    ReactionChecker          -- validates chemical reactions against context
    BiologicalTermChecker    -- validates biological terminology against context
    HallucinationClassifier  -- aggregates all signals into a SentenceVerdict
    HallucinationDetector    -- orchestrator; produces HallucinationReport
    ReportSerializer         -- serialises report to JSON / dict
"""

from __future__ import annotations

import re
import json
import math
import time
import logging
import hashlib
import datetime
import argparse
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, Any

# ---------------------------------------------------------------------------
# Logger
# ---------------------------------------------------------------------------

logger = logging.getLogger("hallucination_detector")
if not logger.handlers:
    _handler = logging.StreamHandler()
    _formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s - %(message)s"
    )
    _handler.setFormatter(_formatter)
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)


# ===========================================================================
# Enumerations
# ===========================================================================

class Subject(str, Enum):
    """Supported NCERT academic subjects."""
    PHYSICS = "Physics"
    BIOLOGY = "Biology"
    CHEMISTRY = "Chemistry"
    GENERAL = "General"


class HallucinationType(str, Enum):
    """Taxonomy of hallucination violations detected."""
    UNSUPPORTED_FACT = "unsupported_fact"
    MISSING_CITATION = "missing_citation"
    EXTERNAL_KNOWLEDGE = "external_knowledge"
    WRONG_EQUATION = "wrong_equation"
    WRONG_DEFINITION = "wrong_definition"
    WRONG_UNIT = "wrong_unit"
    WRONG_REACTION = "wrong_reaction"
    WRONG_BIOLOGICAL_TERM = "wrong_biological_term"
    SUPPORTED = "supported"


class RiskLevel(str, Enum):
    """Risk classification for a detected violation."""
    CRITICAL = "critical"    # score < 0.30
    HIGH = "high"            # score 0.30-0.49
    MEDIUM = "medium"        # score 0.50-0.69
    LOW = "low"              # score 0.70-0.84
    NONE = "none"            # score >= 0.85


# ===========================================================================
# Domain Models  (dataclasses - zero external dependencies)
# ===========================================================================

@dataclass(frozen=True)
class SentenceVerdict:
    """Per-sentence hallucination verdict."""
    sentence_index: int
    sentence_text: str
    support_score: float                    # 0.0 - 1.0  (higher = more supported)
    confidence: float                       # 0.0 - 1.0  (detector confidence)
    hallucination_types: List[HallucinationType]
    risk_level: RiskLevel
    most_similar_context_sentence: str
    evidence_fragments: List[str]           # context fragments supporting/refuting
    is_hallucination: bool
    checker_details: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class SubjectCheckerResult:
    """Result from a domain-specific rule checker."""
    checker_name: str
    flagged: bool
    hallucination_type: Optional[HallucinationType]
    detail: str
    confidence_penalty: float               # subtracted from support_score


@dataclass
class HallucinationReport:
    """Complete hallucination detection report for a single script."""
    # --- Identifiers ---
    report_id: str
    subject: str
    topic: str
    generated_at_utc: str

    # --- Input Metadata ---
    context_sentence_count: int
    script_sentence_count: int
    context_word_count: int
    script_word_count: int

    # --- Aggregate Metrics ---
    overall_faithfulness_score: float
    hallucination_rate: float
    supported_sentence_count: int
    hallucinated_sentence_count: int
    critical_violation_count: int
    high_violation_count: int

    # --- Per-sentence Verdicts ---
    sentence_verdicts: List[SentenceVerdict]

    # --- Summary ---
    unsupported_facts: List[str]
    wrong_equations: List[str]
    wrong_definitions: List[str]
    wrong_units: List[str]
    wrong_reactions: List[str]
    wrong_biological_terms: List[str]
    external_knowledge_claims: List[str]
    missing_citations: List[str]

    # --- Runtime ---
    detection_latency_sec: float
    detector_version: str = "1.0.0"

    def to_dict(self) -> Dict:
        """Convert report to plain dictionary (JSON-serialisable)."""
        def convert(value: Any) -> Any:
            if isinstance(value, Enum):
                return value.value
            if isinstance(value, list):
                return [convert(item) for item in value]
            if isinstance(value, dict):
                return {key: convert(item) for key, item in value.items()}
            return value

        return convert(asdict(self))

    def to_json(self, indent: int = 2) -> str:
        """Serialise report to pretty-printed JSON string."""
        return json.dumps(self.to_dict(), indent=indent, default=str)


# ===========================================================================
# Sentence Segmenter
# ===========================================================================

class SentenceSegmenter:
    """
    Splits text into individual sentences using a rule-based approach that
    handles abbreviations, decimal numbers, and NCERT-style equation blocks.
    """

    _ABBREVIATIONS: Set[str] = {
        "dr", "mr", "mrs", "ms", "prof", "sr", "jr", "vs", "etc",
        "approx", "fig", "eq", "no", "vol", "ch", "ncert",
    }

    @classmethod
    def segment(cls, text: str) -> List[str]:
        """
        Segment *text* into sentences.

        Args:
            text: Raw input text block.

        Returns:
            List of non-empty sentence strings, whitespace-normalised.
        """
        if not text or not text.strip():
            return []

        # Protect decimal numbers: 9.8 -> sentinel
        text = re.sub(r"(\d)\.(\d)", r"\1<DEC>\2", text)

        # Protect known abbreviations
        for abbr in cls._ABBREVIATIONS:
            text = re.sub(
                rf"\b({re.escape(abbr)})\.",
                r"\1<ABBR>",
                text,
                flags=re.IGNORECASE,
            )

        # Split on sentence-ending punctuation followed by whitespace + capital
        sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z\"\'])", text)

        # Restore sentinels
        sentences = [
            s.replace("<DEC>", ".").replace("<ABBR>", ".").strip()
            for s in sentences
        ]

        return [s for s in sentences if len(s.split()) >= 3]


# ===========================================================================
# TF-IDF Vectorizer  (pure Python, no scikit-learn)
# ===========================================================================

class TFIDFVectorizer:
    """
    Lightweight TF-IDF vectorizer operating on token lists.
    Supports fit on a corpus and transform of any text to a sparse dict vector.
    """

    def __init__(self, max_features: int = 5000):
        """
        Args:
            max_features: Maximum vocabulary size (unused in current impl;
                          reserved for future pruning pass).
        """
        self.max_features = max_features
        self._idf: Dict[str, float] = {}
        self._vocab: Set[str] = set()

    def fit(self, corpus: List[str]) -> "TFIDFVectorizer":
        """
        Fit IDF weights from *corpus*.

        Args:
            corpus: Collection of reference documents (context sentences).

        Returns:
            self (for chaining).
        """
        N = len(corpus)
        if N == 0:
            return self

        doc_freq: Counter = Counter()
        tokenised = [self._tokenize(doc) for doc in corpus]

        for tokens in tokenised:
            doc_freq.update(set(tokens))

        self._vocab = set(doc_freq.keys())
        self._idf = {
            term: math.log((N + 1) / (freq + 1)) + 1.0
            for term, freq in doc_freq.items()
        }
        return self

    def transform(self, text: str) -> Dict[str, float]:
        """
        Convert *text* to a TF-IDF weighted sparse vector (dict).

        Args:
            text: Raw text string to vectorize.

        Returns:
            Mapping of term to TF-IDF weight.
        """
        tokens = self._tokenize(text)
        if not tokens:
            return {}

        tf: Counter = Counter(tokens)
        total = len(tokens)
        vector: Dict[str, float] = {}
        for term, count in tf.items():
            tf_val = count / total
            idf_val = self._idf.get(term, math.log(2) + 1.0)  # smooth for OOV
            vector[term] = round(tf_val * idf_val, 6)
        return vector

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Lowercase + alpha-numeric tokenization with stop-word removal."""
        _STOPWORDS = {
            "the", "a", "an", "is", "it", "in", "on", "at", "to", "of",
            "and", "or", "but", "for", "not", "with", "this", "that", "are",
            "was", "be", "as", "by", "from", "has", "have", "had", "its",
        }
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return [t for t in tokens if t not in _STOPWORDS and len(t) > 1]


# ===========================================================================
# Semantic Similarity Engine
# ===========================================================================

class SemanticSimilarityEngine:
    """
    Computes sentence-level semantic similarity between a generated sentence
    and a corpus of retrieved context sentences using TF-IDF cosine similarity
    blended with bigram Jaccard overlap.
    """

    def __init__(self, vectorizer: TFIDFVectorizer):
        """
        Args:
            vectorizer: A TFIDFVectorizer instance (may be pre-fitted or fresh).
        """
        self._vectorizer = vectorizer
        self._context_vectors: List[Tuple[str, Dict[str, float]]] = []

    def index_context(self, context_sentences: List[str]) -> None:
        """
        Fit the vectorizer on *context_sentences* and pre-compute vectors.

        Args:
            context_sentences: List of sentences from the retrieved NCERT context.
        """
        self._vectorizer.fit(context_sentences)
        self._context_vectors = [
            (sent, self._vectorizer.transform(sent))
            for sent in context_sentences
        ]
        logger.debug(f"Indexed {len(self._context_vectors)} context sentences.")

    def best_context_match(
        self, sentence: str
    ) -> Tuple[float, str, List[str]]:
        """
        Find the most semantically similar context sentence for *sentence*.

        Args:
            sentence: A single sentence from the generated script.

        Returns:
            Tuple of:
                best_score (float): Highest blended similarity found (0-1).
                best_sentence (str): The matching context sentence.
                evidence_fragments (List[str]): Top-5 overlapping terms.
        """
        if not self._context_vectors:
            return 0.0, "", []

        query_vec = self._vectorizer.transform(sentence)
        if not query_vec:
            return 0.0, "", []

        best_score = 0.0
        best_sent = ""
        best_evidence: List[str] = []

        for ctx_sent, ctx_vec in self._context_vectors:
            score = self._cosine(query_vec, ctx_vec)
            if score > best_score:
                best_score = score
                best_sent = ctx_sent
                shared = sorted(
                    [t for t in query_vec if t in ctx_vec],
                    key=lambda t: query_vec[t] + ctx_vec[t],
                    reverse=True,
                )
                best_evidence = shared[:5]

        # Blend cosine with bigram Jaccard for robustness
        jaccard = self._bigram_jaccard(sentence, best_sent)
        blended_score = round(0.70 * best_score + 0.30 * jaccard, 4)

        return min(blended_score, 1.0), best_sent, best_evidence

    @staticmethod
    def _cosine(vec_a: Dict[str, float], vec_b: Dict[str, float]) -> float:
        """Cosine similarity between two sparse TF-IDF vectors."""
        if not vec_a or not vec_b:
            return 0.0
        dot = sum(vec_a[t] * vec_b[t] for t in vec_a if t in vec_b)
        mag_a = math.sqrt(sum(v ** 2 for v in vec_a.values()))
        mag_b = math.sqrt(sum(v ** 2 for v in vec_b.values()))
        denom = mag_a * mag_b
        return round(dot / denom, 6) if denom > 0 else 0.0

    @staticmethod
    def _bigram_jaccard(text_a: str, text_b: str) -> float:
        """Bigram Jaccard similarity between two text strings."""
        tokens_a = re.findall(r"[a-z0-9]+", text_a.lower())
        tokens_b = re.findall(r"[a-z0-9]+", text_b.lower())
        bigrams_a = set(zip(tokens_a, tokens_a[1:]))
        bigrams_b = set(zip(tokens_b, tokens_b[1:]))
        union = bigrams_a | bigrams_b
        if not union:
            return 0.0
        return round(len(bigrams_a & bigrams_b) / len(union), 6)


# ===========================================================================
# Subject-Aware Rule Checkers
# ===========================================================================

class EquationChecker:
    """
    Detects mathematical or physics equations in a generated sentence and
    verifies they are grounded in the retrieved context.

    Equations detected: F = ma, E = mc^2, v^2 = u^2 + 2as, lambda = h/mv, etc.
    """

    _EQ_PATTERN = re.compile(
        r"[A-Za-z\u0391-\u03A9\u03B1-\u03C9_]+\s*[=\u2260\u2248\u2264\u2265<>]\s*"
        r"[A-Za-z0-9\u0391-\u03A9\u03B1-\u03C9_\u00B2\u00B3\u221A\+\-\*/\^\(\)\s\.]+",
        re.UNICODE,
    )

    def check(self, sentence: str, context: str) -> SubjectCheckerResult:
        """
        Check whether any equations in *sentence* are present in *context*.

        Args:
            sentence: Generated sentence to inspect.
            context:  Full retrieved context string.

        Returns:
            SubjectCheckerResult indicating if an ungrounded equation was found.
        """
        found_eqs = self._EQ_PATTERN.findall(sentence)
        if not found_eqs:
            return SubjectCheckerResult(
                checker_name="EquationChecker",
                flagged=False,
                hallucination_type=None,
                detail="No equations detected.",
                confidence_penalty=0.0,
            )

        context_lower = context.lower()
        ungrounded = []
        for eq in found_eqs:
            normalised = self._normalize_equation(eq)
            ctx_normalised = re.sub(r"\s+", "", context_lower)
            if normalised not in ctx_normalised:
                ungrounded.append(eq.strip())

        if ungrounded:
            return SubjectCheckerResult(
                checker_name="EquationChecker",
                flagged=True,
                hallucination_type=HallucinationType.WRONG_EQUATION,
                detail=f"Ungrounded equation(s): {'; '.join(ungrounded)}",
                confidence_penalty=0.35,
            )

        return SubjectCheckerResult(
            checker_name="EquationChecker",
            flagged=False,
            hallucination_type=None,
            detail=f"All equations ({len(found_eqs)}) found in context.",
            confidence_penalty=0.0,
        )

    @staticmethod
    def _normalize_equation(equation: str) -> str:
        """Keep the equation core while dropping prose captured after it."""
        cleaned = equation.strip().lower()
        cleaned = re.split(r"\b(where|for|when|if|because|which|that|and|or)\b", cleaned)[0]
        cleaned = cleaned.strip(" .,;:")
        return re.sub(r"\s+", "", cleaned)


class UnitChecker:
    """
    Detects SI / NCERT units mentioned in a generated sentence and verifies
    they appear in the retrieved context.
    """

    _UNIT_PATTERN = re.compile(
        r"(\d[\d\.,]*)\s*"
        r"(m/s\u00B2?|kg/m\u00B3?|n/m\u00B2?|j/kg|m/s|nm|mm|cm|km|mg|\u03BCg|"
        r"ms|\u03BCs|ns|kj|mj|mpa|kpa|kcal|cal|ev|mev|gev|"
        r"mol|[NKJPAVWTFCΩ]|kg|hz|wb|lm|lx|bq|gy|sv)",
        re.UNICODE,
    )

    def check(self, sentence: str, context: str) -> SubjectCheckerResult:
        """
        Verify numeric quantities with units are grounded in *context*.

        Args:
            sentence: Generated sentence to inspect.
            context:  Full retrieved context string.

        Returns:
            SubjectCheckerResult with penalty if ungrounded units detected.
        """
        matches = self._UNIT_PATTERN.findall(sentence)
        if not matches:
            return SubjectCheckerResult(
                checker_name="UnitChecker",
                flagged=False,
                hallucination_type=None,
                detail="No numeric units detected.",
                confidence_penalty=0.0,
            )

        context_lower = context.lower()
        ungrounded = []
        for value, unit in matches:
            quantity = f"{value} {unit}".lower().strip()
            if quantity not in context_lower and value not in context_lower:
                ungrounded.append(quantity)

        if ungrounded:
            return SubjectCheckerResult(
                checker_name="UnitChecker",
                flagged=True,
                hallucination_type=HallucinationType.WRONG_UNIT,
                detail=f"Ungrounded quantities: {'; '.join(ungrounded)}",
                confidence_penalty=0.25,
            )

        return SubjectCheckerResult(
            checker_name="UnitChecker",
            flagged=False,
            hallucination_type=None,
            detail=f"All {len(matches)} quantities grounded in context.",
            confidence_penalty=0.0,
        )


class CitationChecker:
    """
    Detects generated factual sentences that do not carry an explicit citation.

    Missing citations are reported separately from hallucinations because a
    sentence can be factually supported by context while still violating a RAG
    citation policy.
    """

    _CITATION_PATTERN = re.compile(
        r"(\[[0-9,\-\s]+\]|\([A-Za-z][A-Za-z0-9 _.-]+,\s*\d{4}\)|"
        r"\b(?:source|context|ncert|retrieved context)\s*[:#]?\s*\d*\b)",
        re.IGNORECASE,
    )
    _NON_FACTUAL_PREFIX = re.compile(
        r"^\s*(hook|concept|example|memory|neet alert|note|summary)\s*:?\s*$",
        re.IGNORECASE,
    )

    def __init__(self, require_citations: bool = True):
        self.require_citations = require_citations

    def check(self, sentence: str, context: str) -> SubjectCheckerResult:
        if not self.require_citations:
            return SubjectCheckerResult(
                checker_name="CitationChecker",
                flagged=False,
                hallucination_type=None,
                detail="Citation policy disabled.",
                confidence_penalty=0.0,
            )

        if self._NON_FACTUAL_PREFIX.match(sentence) or len(sentence.split()) < 5:
            return SubjectCheckerResult(
                checker_name="CitationChecker",
                flagged=False,
                hallucination_type=None,
                detail="Sentence does not require citation.",
                confidence_penalty=0.0,
            )

        if self._CITATION_PATTERN.search(sentence):
            return SubjectCheckerResult(
                checker_name="CitationChecker",
                flagged=False,
                hallucination_type=None,
                detail="Citation marker detected.",
                confidence_penalty=0.0,
            )

        return SubjectCheckerResult(
            checker_name="CitationChecker",
            flagged=True,
            hallucination_type=HallucinationType.MISSING_CITATION,
            detail="No explicit citation marker found for factual sentence.",
            confidence_penalty=0.0,
        )


class DefinitionChecker:
    """
    Detects definitional claims in a generated sentence and validates them
    against the retrieved context using high-precision trigram overlap.
    """

    _DEF_TRIGGERS = re.compile(
        r"\b(is defined as|refers to|is the|is a|is an|"
        r"is called|is known as|is measured by|is a measure of|"
        r"represents|denotes|is given by)\b",
        re.IGNORECASE,
    )

    def check(self, sentence: str, context: str) -> SubjectCheckerResult:
        """
        Flag definitional claims not supported by context.

        Args:
            sentence: Generated sentence to inspect.
            context:  Full retrieved context string.

        Returns:
            SubjectCheckerResult with penalty if definition is ungrounded.
        """
        if not self._DEF_TRIGGERS.search(sentence):
            return SubjectCheckerResult(
                checker_name="DefinitionChecker",
                flagged=False,
                hallucination_type=None,
                detail="No definitional pattern detected.",
                confidence_penalty=0.0,
            )

        parts = self._DEF_TRIGGERS.split(sentence, maxsplit=1)
        if len(parts) < 3:
            return SubjectCheckerResult(
                checker_name="DefinitionChecker",
                flagged=False,
                hallucination_type=None,
                detail="Could not parse definition body.",
                confidence_penalty=0.0,
            )

        definition_body = parts[-1].strip()
        trigrams_def = self._ngrams(definition_body, 3)
        trigrams_ctx = self._ngrams(context, 3)

        if not trigrams_def:
            return SubjectCheckerResult(
                checker_name="DefinitionChecker",
                flagged=False,
                hallucination_type=None,
                detail="Definition body too short to validate.",
                confidence_penalty=0.0,
            )

        overlap_ratio = len(trigrams_def & trigrams_ctx) / len(trigrams_def)

        if overlap_ratio < 0.30:
            return SubjectCheckerResult(
                checker_name="DefinitionChecker",
                flagged=True,
                hallucination_type=HallucinationType.WRONG_DEFINITION,
                detail=(
                    f"Definition overlap with context is {overlap_ratio:.1%}. "
                    f"Claim: '{sentence[:120]}'"
                ),
                confidence_penalty=0.30,
            )

        return SubjectCheckerResult(
            checker_name="DefinitionChecker",
            flagged=False,
            hallucination_type=None,
            detail=f"Definition grounded (overlap={overlap_ratio:.1%}).",
            confidence_penalty=0.0,
        )

    @staticmethod
    def _ngrams(text: str, n: int) -> Set[Tuple[str, ...]]:
        tokens = re.findall(r"[a-z0-9]+", text.lower())
        return set(tuple(tokens[i: i + n]) for i in range(len(tokens) - n + 1))


class ReactionChecker:
    """
    Chemistry-specific checker: Detects chemical reaction notation and
    verifies it against the retrieved context.
    """

    _REACTION_PATTERN = re.compile(
        r"[A-Z][A-Za-z0-9\u2080-\u2089\u00B2\u00B3\+\-\(\)]*"
        r"(?:\s*\+\s*[A-Z][A-Za-z0-9\u2080-\u2089\u00B2\u00B3\+\-\(\)]*)*"
        r"\s*(?:\u2192|->|\u27F6|yields?|produces?|gives?)\s*"
        r"[A-Z][A-Za-z0-9\u2080-\u2089\u00B2\u00B3\+\-\(\)]*",
        re.UNICODE,
    )

    def check(self, sentence: str, context: str) -> SubjectCheckerResult:
        """
        Flag chemical reactions in *sentence* not grounded in *context*.

        Args:
            sentence: Generated sentence to inspect.
            context:  Full retrieved context string.

        Returns:
            SubjectCheckerResult with penalty if ungrounded reaction found.
        """
        reactions = self._REACTION_PATTERN.findall(sentence)
        if not reactions:
            return SubjectCheckerResult(
                checker_name="ReactionChecker",
                flagged=False,
                hallucination_type=None,
                detail="No chemical reactions detected.",
                confidence_penalty=0.0,
            )

        context_lower = context.lower()
        ungrounded = []
        for rxn in reactions:
            rxn_ascii = rxn.replace("\u2192", "->").strip().lower()
            if rxn_ascii not in context_lower and rxn.strip().lower() not in context_lower:
                ungrounded.append(rxn.strip())

        if ungrounded:
            return SubjectCheckerResult(
                checker_name="ReactionChecker",
                flagged=True,
                hallucination_type=HallucinationType.WRONG_REACTION,
                detail=f"Ungrounded reaction(s): {'; '.join(ungrounded)}",
                confidence_penalty=0.40,
            )

        return SubjectCheckerResult(
            checker_name="ReactionChecker",
            flagged=False,
            hallucination_type=None,
            detail=f"All {len(reactions)} reaction(s) grounded in context.",
            confidence_penalty=0.0,
        )


class BiologicalTermChecker:
    """
    Biology-specific checker: Detects NCERT biological terminology, scientific
    binomials, and process keywords; verifies their presence in context.
    """

    _SCIENTIFIC_NAME_PATTERN = re.compile(
        r"\b([A-Z][a-z]+\s+[a-z]+)\b"
    )
    _BIO_PROCESS_TERMS: Set[str] = {
        "photosynthesis", "respiration", "meiosis", "mitosis", "transcription",
        "translation", "replication", "glycolysis", "osmosis", "diffusion",
        "plasmolysis", "turgidity", "imbibition", "guttation",
        "transpiration", "germination", "pollination", "fertilization",
        "cleavage", "gastrulation", "metamorphosis", "regeneration",
        "sporulation", "conjugation", "xylem", "phloem", "stomata",
        "chloroplast", "mitochondria", "ribosome", "nucleolus", "centrosome",
        "vacuole", "lysosome", "peroxisome",
    }

    _BIO_PROCESS_KEYWORDS = re.compile(
        r"\b(photosynthesis|respiration|meiosis|mitosis|transcription|"
        r"translation|replication|glycolysis|krebs cycle|oxidative phosphorylation|"
        r"osmosis|diffusion|active transport|endocytosis|exocytosis|"
        r"plasmolysis|turgidity|imbibition|guttation|transpiration|"
        r"germination|pollination|fertilization|cleavage|gastrulation|"
        r"metamorphosis|regeneration|sporulation|conjugation|"
        r"crossing over|synapsis|bivalent|chiasmata|tracheids|"
        r"companion cells|sieve tubes|xylem|phloem|stomata|guard cells|"
        r"chloroplast|mitochondria|ribosome|golgi body|endoplasmic reticulum|"
        r"nucleolus|centrosome|vacuole|lysosome|peroxisome)\b",
        re.IGNORECASE,
    )
    _COMMON_SECOND_WORDS: Set[str] = {
        "occurs", "is", "are", "was", "were", "has", "have", "produces",
        "converts", "requires", "uses", "forms", "contains", "includes",
    }

    def check(self, sentence: str, context: str) -> SubjectCheckerResult:
        """
        Flag biological terms in *sentence* not grounded in *context*.

        Args:
            sentence: Generated sentence to inspect.
            context:  Full retrieved context string.

        Returns:
            SubjectCheckerResult with penalty if ungrounded bio terms found.
        """
        flagged_terms: List[str] = []
        context_lower = context.lower()

        sci_names = self._SCIENTIFIC_NAME_PATTERN.findall(sentence)
        for name in sci_names:
            first, second = name.split(maxsplit=1)
            if (
                first.lower() in self._BIO_PROCESS_TERMS
                or second.lower() in self._COMMON_SECOND_WORDS
            ):
                continue
            if name.lower() not in context_lower:
                flagged_terms.append(name)

        bio_procs = self._BIO_PROCESS_KEYWORDS.findall(sentence)
        for proc in bio_procs:
            if proc.lower() not in context_lower:
                flagged_terms.append(proc)

        if flagged_terms:
            return SubjectCheckerResult(
                checker_name="BiologicalTermChecker",
                flagged=True,
                hallucination_type=HallucinationType.WRONG_BIOLOGICAL_TERM,
                detail=f"Ungrounded bio term(s): {'; '.join(set(flagged_terms))}",
                confidence_penalty=0.30,
            )

        return SubjectCheckerResult(
            checker_name="BiologicalTermChecker",
            flagged=False,
            hallucination_type=None,
            detail="All biological terms grounded in context.",
            confidence_penalty=0.0,
        )


# ===========================================================================
# Hallucination Classifier
# ===========================================================================

class HallucinationClassifier:
    """
    Combines semantic similarity score and subject-aware checker signals into
    a final per-sentence SentenceVerdict.

    Scoring:
        base_score   = semantic similarity (0-1)
        penalty      = sum of checker confidence_penalties
        final_score  = clamp(base_score - penalty, 0.0, 1.0)
        is_hallucination = final_score < HALLUCINATION_THRESHOLD
    """

    HALLUCINATION_THRESHOLD: float = 0.45

    def classify(
        self,
        sentence_index: int,
        sentence: str,
        similarity_score: float,
        best_context_sentence: str,
        evidence_fragments: List[str],
        checker_results: List[SubjectCheckerResult],
    ) -> SentenceVerdict:
        """
        Produce a SentenceVerdict from aggregated signals.

        Args:
            sentence_index:       Position index of sentence in script.
            sentence:             The generated sentence text.
            similarity_score:     Semantic cosine similarity (0-1).
            best_context_sentence:Most similar context sentence.
            evidence_fragments:   Shared vocabulary terms.
            checker_results:      Results from all subject-aware checkers.

        Returns:
            SentenceVerdict with support_score, risk_level, and hallucination flag.
        """
        total_penalty = sum(r.confidence_penalty for r in checker_results if r.flagged)
        support_score = round(max(0.0, min(1.0, similarity_score - total_penalty)), 4)

        hall_types: List[HallucinationType] = [
            r.hallucination_type
            for r in checker_results
            if r.flagged and r.hallucination_type
        ]
        if support_score < self.HALLUCINATION_THRESHOLD and not hall_types:
            hall_types.append(HallucinationType.UNSUPPORTED_FACT)
        if support_score < 0.20 and not evidence_fragments:
            if HallucinationType.EXTERNAL_KNOWLEDGE not in hall_types:
                hall_types.append(HallucinationType.EXTERNAL_KNOWLEDGE)
        if not hall_types:
            hall_types.append(HallucinationType.SUPPORTED)

        is_hallucination = support_score < self.HALLUCINATION_THRESHOLD

        distance = abs(support_score - self.HALLUCINATION_THRESHOLD)
        confidence = round(min(1.0, 0.50 + distance * 1.5), 4)

        risk = self._classify_risk(support_score)

        return SentenceVerdict(
            sentence_index=sentence_index,
            sentence_text=sentence,
            support_score=support_score,
            confidence=confidence,
            hallucination_types=hall_types,
            risk_level=risk,
            most_similar_context_sentence=best_context_sentence,
            evidence_fragments=evidence_fragments,
            is_hallucination=is_hallucination,
            checker_details=[
                {
                    "checker_name": result.checker_name,
                    "flagged": result.flagged,
                    "hallucination_type": (
                        result.hallucination_type.value
                        if result.hallucination_type
                        else None
                    ),
                    "detail": result.detail,
                    "confidence_penalty": result.confidence_penalty,
                }
                for result in checker_results
            ],
        )

    @staticmethod
    def _classify_risk(score: float) -> RiskLevel:
        if score < 0.30:
            return RiskLevel.CRITICAL
        if score < 0.50:
            return RiskLevel.HIGH
        if score < 0.70:
            return RiskLevel.MEDIUM
        if score < 0.85:
            return RiskLevel.LOW
        return RiskLevel.NONE


# ===========================================================================
# Hallucination Detector  (Orchestrator)
# ===========================================================================

class HallucinationDetector:
    """
    Production-ready hallucination detector for NCERT RAG-generated scripts.

    Orchestrates:
        1. SentenceSegmenter     -- splits context + script into sentences
        2. SemanticSimilarityEngine -- indexes context, scores each sentence
        3. Subject-aware checkers   -- equations, units, definitions, etc.
        4. HallucinationClassifier  -- aggregates signals to per-sentence verdicts
        5. HallucinationReport      -- structured JSON-serialisable report

    No external dependencies; runs on pure Python 3.9+.

    Usage::

        detector = HallucinationDetector(subject=Subject.PHYSICS)
        report   = detector.detect(
            retrieved_context="NCERT text...",
            generated_script="LLM output...",
            topic="Newton Laws",
        )
        print(report.to_json())
    """

    DETECTOR_VERSION: str = "1.0.0"

    def __init__(
        self,
        subject: Subject = Subject.GENERAL,
        hallucination_threshold: float = 0.45,
        tfidf_max_features: int = 5000,
        require_citations: bool = True,
    ):
        """
        Initialise detector with subject-specific checker selection.

        Args:
            subject:               Academic subject for rule selection.
            hallucination_threshold: Sentences scoring below this are flagged.
            tfidf_max_features:    Vocabulary limit for TF-IDF vectorizer.
            require_citations:     Whether factual generated sentences must
                                   include explicit citation markers.
        """
        self.subject = subject
        self.hallucination_threshold = hallucination_threshold
        self.require_citations = require_citations

        self._segmenter = SentenceSegmenter()
        self._vectorizer = TFIDFVectorizer(max_features=tfidf_max_features)
        self._similarity_engine = SemanticSimilarityEngine(self._vectorizer)
        self._classifier = HallucinationClassifier()
        self._classifier.HALLUCINATION_THRESHOLD = hallucination_threshold
        self._checkers = self._build_checkers(subject, require_citations)

        logger.info(
            f"HallucinationDetector v{self.DETECTOR_VERSION} initialised "
            f"[subject={subject.value}, threshold={hallucination_threshold}, "
            f"require_citations={require_citations}]"
        )

    def detect(
        self,
        retrieved_context: str,
        generated_script: str,
        topic: str = "Unknown",
    ) -> HallucinationReport:
        """
        Run the full hallucination detection pipeline.

        Args:
            retrieved_context: Raw NCERT retrieved context text.
            generated_script:  LLM-generated teaching script text.
            topic:             Topic name for report metadata.

        Returns:
            HallucinationReport with per-sentence verdicts and aggregate metrics.

        Raises:
            ValueError: If context or script is empty.
        """
        if not retrieved_context or not retrieved_context.strip():
            raise ValueError("retrieved_context must be a non-empty string.")
        if not generated_script or not generated_script.strip():
            raise ValueError("generated_script must be a non-empty string.")

        start_time = time.monotonic()
        logger.info(f"Starting hallucination detection | topic='{topic}'")

        # 1. Segment
        context_sentences = self._segmenter.segment(retrieved_context)
        script_sentences = self._segmenter.segment(generated_script)
        if not context_sentences:
            context_sentences = [retrieved_context.strip()]
        if not script_sentences:
            script_sentences = [generated_script.strip()]

        logger.debug(
            f"Segmented: {len(context_sentences)} context sentences, "
            f"{len(script_sentences)} script sentences."
        )

        # 2. Index context
        self._similarity_engine.index_context(context_sentences)

        # 3. Evaluate each sentence
        verdicts: List[SentenceVerdict] = [
            self._evaluate_sentence(idx, sent, retrieved_context)
            for idx, sent in enumerate(script_sentences)
        ]

        # 4. Aggregate and return
        report = self._build_report(
            topic=topic,
            context_sentences=context_sentences,
            script_sentences=script_sentences,
            verdicts=verdicts,
            context_text=retrieved_context,
            script_text=generated_script,
            latency=time.monotonic() - start_time,
        )

        logger.info(
            f"Detection complete | faithfulness={report.overall_faithfulness_score:.3f} "
            f"| hallucination_rate={report.hallucination_rate:.1%} "
            f"| latency={report.detection_latency_sec:.3f}s"
        )
        return report

    # ------------------------------------------------------------------
    # Internal pipeline steps
    # ------------------------------------------------------------------

    def _evaluate_sentence(
        self,
        idx: int,
        sentence: str,
        full_context: str,
    ) -> SentenceVerdict:
        """Run similarity + checkers on one sentence and return its verdict."""
        sim_score, best_ctx_sent, evidence = (
            self._similarity_engine.best_context_match(sentence)
        )
        checker_results: List[SubjectCheckerResult] = [
            checker.check(sentence, full_context)
            for checker in self._checkers
        ]
        return self._classifier.classify(
            sentence_index=idx,
            sentence=sentence,
            similarity_score=sim_score,
            best_context_sentence=best_ctx_sent,
            evidence_fragments=evidence,
            checker_results=checker_results,
        )

    def _build_report(
        self,
        topic: str,
        context_sentences: List[str],
        script_sentences: List[str],
        verdicts: List[SentenceVerdict],
        context_text: str,
        script_text: str,
        latency: float,
    ) -> HallucinationReport:
        """Aggregate per-sentence verdicts into a final HallucinationReport."""
        hallucinated = [v for v in verdicts if v.is_hallucination]
        supported = [v for v in verdicts if not v.is_hallucination]

        faithfulness_score = round(
            sum(v.support_score for v in verdicts) / max(len(verdicts), 1), 4
        )
        hallucination_rate = round(
            len(hallucinated) / max(len(verdicts), 1), 4
        )

        unsupported_facts: List[str] = []
        wrong_equations: List[str] = []
        wrong_definitions: List[str] = []
        wrong_units: List[str] = []
        wrong_reactions: List[str] = []
        wrong_bio_terms: List[str] = []
        external_knowledge: List[str] = []
        missing_citations: List[str] = []

        for v in verdicts:
            types = set(v.hallucination_types)
            if HallucinationType.UNSUPPORTED_FACT in types:
                unsupported_facts.append(v.sentence_text)
            if HallucinationType.WRONG_EQUATION in types:
                wrong_equations.append(v.sentence_text)
            if HallucinationType.WRONG_DEFINITION in types:
                wrong_definitions.append(v.sentence_text)
            if HallucinationType.WRONG_UNIT in types:
                wrong_units.append(v.sentence_text)
            if HallucinationType.WRONG_REACTION in types:
                wrong_reactions.append(v.sentence_text)
            if HallucinationType.WRONG_BIOLOGICAL_TERM in types:
                wrong_bio_terms.append(v.sentence_text)
            if HallucinationType.EXTERNAL_KNOWLEDGE in types:
                external_knowledge.append(v.sentence_text)
            if HallucinationType.MISSING_CITATION in types:
                missing_citations.append(v.sentence_text)

        # External knowledge heuristic: very low score with no evidence
        for v in hallucinated:
            if v.support_score < 0.20 and not v.evidence_fragments:
                if v.sentence_text not in external_knowledge:
                    external_knowledge.append(v.sentence_text)

        critical_count = sum(1 for v in hallucinated if v.risk_level == RiskLevel.CRITICAL)
        high_count = sum(1 for v in hallucinated if v.risk_level == RiskLevel.HIGH)

        report_id = hashlib.sha256(
            f"{topic}{time.monotonic()}".encode()
        ).hexdigest()[:16]

        generated_at = datetime.datetime.utcnow().isoformat() + "Z"

        return HallucinationReport(
            report_id=report_id,
            subject=self.subject.value,
            topic=topic,
            generated_at_utc=generated_at,
            context_sentence_count=len(context_sentences),
            script_sentence_count=len(script_sentences),
            context_word_count=len(context_text.split()),
            script_word_count=len(script_text.split()),
            overall_faithfulness_score=faithfulness_score,
            hallucination_rate=hallucination_rate,
            supported_sentence_count=len(supported),
            hallucinated_sentence_count=len(hallucinated),
            critical_violation_count=critical_count,
            high_violation_count=high_count,
            sentence_verdicts=verdicts,
            unsupported_facts=unsupported_facts,
            wrong_equations=wrong_equations,
            wrong_definitions=wrong_definitions,
            wrong_units=wrong_units,
            wrong_reactions=wrong_reactions,
            wrong_biological_terms=wrong_bio_terms,
            external_knowledge_claims=external_knowledge,
            missing_citations=missing_citations,
            detection_latency_sec=round(latency, 4),
            detector_version=self.DETECTOR_VERSION,
        )

    @staticmethod
    def _build_checkers(subject: Subject, require_citations: bool = True) -> List:
        """
        Return the appropriate set of rule checkers for *subject*.

        Physics   -> EquationChecker, UnitChecker, DefinitionChecker
        Biology   -> BiologicalTermChecker, DefinitionChecker
        Chemistry -> ReactionChecker, EquationChecker, UnitChecker, DefinitionChecker
        General   -> DefinitionChecker, UnitChecker
        """
        definition_checker = DefinitionChecker()
        unit_checker = UnitChecker()
        equation_checker = EquationChecker()
        reaction_checker = ReactionChecker()
        bio_checker = BiologicalTermChecker()
        citation_checker = CitationChecker(require_citations=require_citations)

        mapping: Dict[Subject, List] = {
            Subject.PHYSICS: [equation_checker, unit_checker, definition_checker, citation_checker],
            Subject.BIOLOGY: [bio_checker, definition_checker, citation_checker],
            Subject.CHEMISTRY: [reaction_checker, equation_checker, unit_checker, definition_checker, citation_checker],
            Subject.GENERAL: [definition_checker, unit_checker, citation_checker],
        }
        return mapping.get(subject, [definition_checker])


# ===========================================================================
# Report Serializer
# ===========================================================================

class ReportSerializer:
    """
    Utility for serialising HallucinationReport to multiple formats.

    Supported outputs:
        - JSON string (pretty-printed)
        - Python dict
        - Compact JSON (minified)
        - Summary dict (key metrics only)
    """

    @staticmethod
    def to_json(report: HallucinationReport, indent: int = 2) -> str:
        """Pretty-printed JSON string."""
        return report.to_json(indent=indent)

    @staticmethod
    def to_dict(report: HallucinationReport) -> Dict:
        """Plain Python dict."""
        return report.to_dict()

    @staticmethod
    def to_compact_json(report: HallucinationReport) -> str:
        """Minified JSON for storage/transmission."""
        return json.dumps(report.to_dict(), separators=(",", ":"), default=str)

    @staticmethod
    def to_summary(report: HallucinationReport) -> Dict:
        """Concise summary dict with key metrics only."""
        return {
            "report_id": report.report_id,
            "subject": report.subject,
            "topic": report.topic,
            "generated_at_utc": report.generated_at_utc,
            "overall_faithfulness_score": report.overall_faithfulness_score,
            "hallucination_rate": report.hallucination_rate,
            "supported_sentence_count": report.supported_sentence_count,
            "hallucinated_sentence_count": report.hallucinated_sentence_count,
            "critical_violations": report.critical_violation_count,
            "high_violations": report.high_violation_count,
            "unsupported_facts_count": len(report.unsupported_facts),
            "wrong_equations_count": len(report.wrong_equations),
            "wrong_units_count": len(report.wrong_units),
            "wrong_reactions_count": len(report.wrong_reactions),
            "wrong_biological_terms_count": len(report.wrong_biological_terms),
            "wrong_definitions_count": len(report.wrong_definitions),
            "external_knowledge_count": len(report.external_knowledge_claims),
            "missing_citations_count": len(report.missing_citations),
            "detection_latency_sec": report.detection_latency_sec,
            "detector_version": report.detector_version,
        }


# ===========================================================================
# Module-level convenience function
# ===========================================================================

def detect_hallucinations(
    retrieved_context: str,
    generated_script: str,
    subject: str = "General",
    topic: str = "Unknown",
    hallucination_threshold: float = 0.45,
    require_citations: bool = True,
) -> HallucinationReport:
    """
    Convenience entry-point for one-shot hallucination detection.

    Args:
        retrieved_context:       NCERT retrieved context text.
        generated_script:        LLM-generated teaching script.
        subject:                 One of "Physics", "Biology", "Chemistry", "General".
        topic:                   Descriptive topic name for the report.
        hallucination_threshold: Float (0-1); sentences scoring below this are flagged.
        require_citations:       Whether generated factual sentences must include
                                 citation markers such as [1] or source: 1.

    Returns:
        HallucinationReport with sentence-level verdicts and JSON output.

    Example::

        report = detect_hallucinations(
            retrieved_context="Newton's first law states...",
            generated_script="HOOK:\\nEvery object at rest...",
            subject="Physics",
            topic="Newton's Laws of Motion",
        )
        print(report.to_json())
    """
    try:
        subject_enum = Subject(subject)
    except ValueError:
        logger.warning(f"Unknown subject '{subject}'; defaulting to General.")
        subject_enum = Subject.GENERAL

    detector = HallucinationDetector(
        subject=subject_enum,
        hallucination_threshold=hallucination_threshold,
        require_citations=require_citations,
    )
    return detector.detect(
        retrieved_context=retrieved_context,
        generated_script=generated_script,
        topic=topic,
    )


# ===========================================================================
# Command-line interface
# ===========================================================================

def _read_text_arg(value: Optional[str], file_path: Optional[str], label: str) -> str:
    """Read text from either a direct CLI value or a file path."""
    if value and file_path:
        raise ValueError(f"Pass either --{label} or --{label}-file, not both.")
    if file_path:
        with open(file_path, "r", encoding="utf-8") as handle:
            return handle.read()
    if value:
        return value
    raise ValueError(f"Missing required input: --{label} or --{label}-file.")


def build_arg_parser() -> argparse.ArgumentParser:
    """Build the production CLI argument parser."""
    parser = argparse.ArgumentParser(
        description=(
            "Detect hallucinations in a generated educational script by "
            "comparing it sentence-by-sentence against retrieved context."
        )
    )
    parser.add_argument("--context", help="Retrieved context text.")
    parser.add_argument("--context-file", help="Path to a UTF-8 retrieved context file.")
    parser.add_argument("--script", help="Generated script text.")
    parser.add_argument("--script-file", help="Path to a UTF-8 generated script file.")
    parser.add_argument(
        "--subject",
        default="General",
        choices=[subject.value for subject in Subject],
        help="Academic subject used for domain-specific checks.",
    )
    parser.add_argument("--topic", default="Unknown", help="Topic label for the report.")
    parser.add_argument(
        "--threshold",
        type=float,
        default=0.45,
        help="Support-score threshold below which a sentence is hallucinated.",
    )
    parser.add_argument(
        "--no-citation-check",
        action="store_true",
        help="Disable missing-citation detection.",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Emit only aggregate report metrics.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit minified JSON.",
    )
    parser.add_argument(
        "--output",
        help="Optional path to write the JSON report. Prints to stdout when omitted.",
    )
    parser.add_argument(
        "--log-level",
        default="WARNING",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Logging level for detector diagnostics.",
    )
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entry point. Returns a process exit code."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    logger.setLevel(getattr(logging, args.log_level))

    try:
        retrieved_context = _read_text_arg(args.context, args.context_file, "context")
        generated_script = _read_text_arg(args.script, args.script_file, "script")
        if not 0.0 <= args.threshold <= 1.0:
            raise ValueError("--threshold must be between 0.0 and 1.0.")

        report = detect_hallucinations(
            retrieved_context=retrieved_context,
            generated_script=generated_script,
            subject=args.subject,
            topic=args.topic,
            hallucination_threshold=args.threshold,
            require_citations=not args.no_citation_check,
        )
        payload: Any = (
            ReportSerializer.to_summary(report)
            if args.summary
            else ReportSerializer.to_dict(report)
        )
        json_output = json.dumps(
            payload,
            indent=None if args.compact else 2,
            separators=(",", ":") if args.compact else None,
            default=str,
        )

        if args.output:
            with open(args.output, "w", encoding="utf-8") as handle:
                handle.write(json_output)
                handle.write("\n")
        else:
            print(json_output)
        return 0
    except Exception as exc:
        print(f"hallucination_detector error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
