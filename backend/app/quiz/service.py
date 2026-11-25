"""Quiz generation: Gemini when it can, the textbook text itself when it cannot.

The quiz is its own service. It shares the retriever with the video pipeline and
nothing else: no job, no queue, no scenes. A student can ask for a quiz on a
topic they never watched, and asking for one does not slow a video down — the
only shared resource is the retrieval model, and a quiz takes one retrieval.

Order of attempts
-----------------
1. Retrieve the textbook passages for the topic (same retriever as the video).
2. Ask Gemini for the questions, with a hard time limit. Every question it
   returns is validated, including a check that its quoted source really is in
   the retrieved text; anything that fails is dropped.
3. Top up from the rule-based generator, which needs no network. If Gemini is
   down, slow or wrong, the whole quiz comes from here.

Each question records which generator wrote it, and the quiz records a note when
it fell back, so the difference is visible rather than silent.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.core.config import get_settings
from app.llm.gemini_service import GeminiUnavailable, describe_gemini_failure, gemini_service
from app.llm.llm_router import AllProvidersFailedError, acall_llm, is_task_configured
from app.quiz import rule_based
from app.quiz.rule_based import Question, citation_for
from app.quiz.validation import _trigrams, _words, validate_item
from app.rag.retriever import retriever

logger = logging.getLogger(__name__)

MIN_QUESTIONS = 3
MAX_QUESTIONS = 10
DEFAULT_QUESTIONS = 5
RETRIEVAL_TOP_K = 10


class QuizUnavailable(Exception):
    """A quiz could not be produced; ``message`` is safe to show the student."""

    def __init__(self, message: str, status_code: int = 422) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass
class GeneratedQuiz:
    topic: str               # label used for mastery tracking: the chapter name
    requested_topic: str
    subject: Optional[str]
    class_level: Optional[str]
    questions: List[Question]
    generator: str           # "gemini" | "rule_based" | "mixed"
    notes: List[str] = field(default_factory=list)


def mix_for(count: int) -> Dict[str, int]:
    """How many EASY / MEDIUM / HARD questions a quiz of ``count`` should hold."""
    easy = round(count * 0.4)
    hard = max(1, round(count * 0.2))
    return {"EASY": easy, "MEDIUM": count - easy - hard, "HARD": hard}


def _not_found_message(topic: str) -> str:
    return (
        f"“{topic}” was not found in the indexed NCERT textbooks. Try a Class 11 "
        "or 12 Physics, Chemistry or Biology topic, for example “Photosynthesis”, "
        "“Laws of Motion” or “Chemical Kinetics”."
    )


# --------------------------------------------------------------------------
# Gemini
# --------------------------------------------------------------------------

_SYSTEM = (
    "You write multiple-choice questions for NEET aspirants from NCERT textbook "
    "passages. Use only facts stated in the passages. Never use outside knowledge."
)


def _prompt(topic: str, subject: str, class_level: str, context: str, mix: Dict[str, int]) -> str:
    wanted = ", ".join(f"{count} {level}" for level, count in mix.items() if count)
    return f"""Write {sum(mix.values())} multiple-choice questions ({wanted}) on "{topic}" for Class {class_level} {subject}.

RULES
- Every question and its correct answer must be stated in the PASSAGES below.
- EASY = recall a definition or fact. MEDIUM = connect two facts or pick the right term. HARD = apply a stated rule to a case, or tell apart two close ideas.
- Exactly four options. One is correct; the other three are plausible but clearly wrong according to the passages.
- The student will NOT see the passages, so never write "according to the passage" or "the text above".
- "source_quote" must be copied word for word from the passages: the single sentence that proves the answer (at least 8 words).
- "explanation" is one or two sentences saying why the answer is right, using the textbook's wording.

Return ONLY a JSON object, no other text, in this shape:
{{"questions": [
  {{
    "question": "...",
    "options": {{"A": "...", "B": "...", "C": "...", "D": "..."}},
    "correct_option": "B",
    "difficulty": "EASY",
    "explanation": "...",
    "source_quote": "..."
  }}
]}}

PASSAGES
{context}
"""


async def _llm(prompt: str, system: str) -> str:
    """The quiz's AI call: route "quiz_generate" (Groq -> Gemini -> OpenRouter)."""
    text, provider = await acall_llm("quiz_generate", prompt, system=system, json_mode=True, max_tokens=4096)
    logger.info("Quiz questions written by %s", provider)
    return text


async def _ask_gemini(topic, subject, class_level, context, mix) -> list:
    raw = await _llm(_prompt(topic, subject, class_level, context, mix), _SYSTEM)
    parsed = gemini_service._extract_json_block(raw)
    if isinstance(parsed, dict):
        parsed = parsed.get("questions") or next((v for v in parsed.values() if isinstance(v, list)), [])
    if not isinstance(parsed, list):
        raise ValueError("Gemini did not return a JSON list of questions")
    return parsed


def _citation_for_quote(quote: str, chunks) -> str:
    """The retrieved chunk that contains most of ``quote``."""
    grams = _trigrams(_words(quote))
    best, best_hits = None, 0
    for chunk in chunks:
        hits = len(grams & _trigrams(_words(chunk.content)))
        if hits > best_hits:
            best, best_hits = chunk, hits
    return citation_for(best) if best else ""


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------

async def generate_quiz(
    topic: str,
    subject: Optional[str] = None,
    class_level: Optional[str] = None,
    num_questions: int = DEFAULT_QUESTIONS,
) -> GeneratedQuiz:
    settings = get_settings()
    count = max(MIN_QUESTIONS, min(MAX_QUESTIONS, int(num_questions)))
    mix = mix_for(count)

    # Retrieval is synchronous (embedding model + Qdrant). A thread keeps the
    # event loop free for everything else the server is doing, including the
    # status polls of a video that is being rendered.
    result = None
    for attempt in (1, 2):
        try:
            result = await asyncio.to_thread(
                retriever.retrieve,
                topic,
                top_k=RETRIEVAL_TOP_K,
                subject=subject,
                class_level=class_level,
                caller="Quiz",
            )
        except Exception as exc:
            logger.exception("Quiz retrieval failed for %r", topic)
            raise QuizUnavailable(f"The textbook search failed: {exc}", 503) from exc
        # A match score of exactly 0.0 means the topic lookup itself failed (a
        # dropped connection to Qdrant is reported that way), not that the
        # topic matched badly. That is worth one more try before telling the
        # student their topic is not in the textbook.
        if result.filters_applied.get("topic_matched", True) or result.filters_applied.get("match_score", 0.0) > 0.0:
            break
        logger.warning("Quiz %r: topic lookup returned no score (attempt %s); retrying", topic, attempt)

    applied = result.filters_applied
    if not result.chunks or not applied.get("topic_matched", True):
        raise QuizUnavailable(_not_found_message(topic), 404)

    subject = applied.get("resolved_subject") or subject
    class_level = applied.get("resolved_class_level") or class_level
    chapters = Counter(c.chapter_name for c in result.chunks if c.chapter_name)
    label = chapters.most_common(1)[0][0] if chapters else topic

    rng = random.Random()
    notes: List[str] = []
    questions: List[Question] = []

    # ---- 1. Gemini ------------------------------------------------------
    if settings.quiz_llm_enabled and is_task_configured("quiz_generate"):
        try:
            items = await asyncio.wait_for(
                _ask_gemini(topic, subject or "Science", class_level or "11", result.context_text, mix),
                timeout=settings.quiz_llm_timeout_seconds,
            )
            valid = []
            for item in items:
                question = validate_item(item, result.context_text, rng)
                if question:
                    question.citation = _citation_for_quote(question.source_quote, result.chunks)
                    valid.append(question)
            logger.info(
                "Quiz %r: AI status: WORKING - %s question(s) returned, %s passed validation",
                topic, len(items), len(valid),
            )
            dropped = len(items) - len(valid)
            if dropped:
                notes.append(f"{dropped} AI-written question(s) failed the textbook-grounding check and were dropped.")
            questions = _pick(valid, mix, count)
        except (GeminiUnavailable, AllProvidersFailedError, asyncio.TimeoutError) as exc:
            logger.warning(
                "Quiz %r: AI status: %s - using the textbook text instead",
                topic, describe_gemini_failure(exc),
            )
            notes.append("The AI models were unavailable, so these questions were built directly from the textbook text.")
        except Exception:
            logger.exception("Quiz %r: AI question generation failed", topic)
            notes.append("The AI could not produce a usable quiz, so these questions were built directly from the textbook text.")
    elif not is_task_configured("quiz_generate"):
        notes.append("No AI API key is configured; questions were built directly from the textbook text.")

    # ---- 2. Rule-based top-up ------------------------------------------
    if len(questions) < count:
        have = Counter(q.difficulty for q in questions)
        need = {level: max(0, mix[level] - have[level]) for level in mix}
        shortfall = count - len(questions)
        # Ask for the full shortfall; generate() fills any difficulty it cannot.
        if sum(need.values()) < shortfall:
            need["MEDIUM"] += shortfall - sum(need.values())
        extra = await asyncio.to_thread(
            rule_based.generate,
            result.chunks,
            topic,
            need,
            None,
            [q.source_quote for q in questions],
        )
        questions.extend(extra[:shortfall])

    if not questions:
        raise QuizUnavailable(
            f"There is not enough usable textbook text on “{topic}” to build a quiz. "
            "Try a broader topic or the chapter name.",
            422,
        )
    if len(questions) < count:
        notes.append(f"Only {len(questions)} question(s) could be built from the textbook text on this topic.")

    sources = {q.source for q in questions}
    generator = "mixed" if len(sources) > 1 else sources.pop()
    return GeneratedQuiz(
        topic=label,
        requested_topic=topic,
        subject=subject,
        class_level=str(class_level) if class_level is not None else None,
        questions=questions,
        generator=generator,
        notes=notes,
    )


def _pick(valid: List[Question], mix: Dict[str, int], count: int) -> List[Question]:
    """Up to ``count`` valid questions, honouring ``mix`` where the model allowed."""
    chosen: List[Question] = []
    remaining = list(valid)
    for level, wanted in mix.items():
        for question in [q for q in remaining if q.difficulty == level][:wanted]:
            chosen.append(question)
            remaining.remove(question)
    chosen.extend(remaining[: max(0, count - len(chosen))])
    return chosen[:count]
