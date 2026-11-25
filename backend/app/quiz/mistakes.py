"""Label a wrong quiz answer as a conceptual, calculation or silly mistake.

An AI model (via the LLM router) reads the question, the student's pick and the right answer and says
which kind of slip it was, with one short sentence for the student. When no AI provider
is configured, times out or replies with something unusable, a simple rule
gives the label instead, so every wrong answer always has one.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from app.core.config import get_settings
from app.llm.gemini_service import gemini_service
from app.llm.llm_router import acall_llm, is_task_configured

logger = logging.getLogger(__name__)

KINDS = ("conceptual", "calculation", "silly")
_NUMBER = re.compile(r"\d")
# Ability (−3…3) at or above which an EASY question "should" be answered right.
_EASY_LEVEL = -1.0

_SYSTEM = (
    "You are a NEET tutor reviewing one wrong answer on a multiple-choice question "
    "from an NCERT Class 11/12 textbook. Classify the mistake and explain it briefly "
    "to the student. Reply with JSON only."
)


def classify_by_rule(question: dict, difficulty: str, ability: float) -> str:
    """Fallback label: numeric question -> calculation; missed easy one -> silly; else conceptual."""
    text = " ".join([str(question.get("question", ""))] + [str(v) for v in (question.get("options") or {}).values()])
    if len(_NUMBER.findall(text)) >= 3:
        return "calculation"
    if difficulty == "EASY" and ability > _EASY_LEVEL:
        return "silly"
    return "conceptual"


def _prompt(question: dict, selected: str, correct: str, difficulty: str) -> str:
    options = question.get("options") or {}
    lines = "\n".join(f"{k}. {v}" for k, v in sorted(options.items()))
    return f"""Question ({difficulty.lower()} difficulty):
{question.get("question", "")}

Options:
{lines}

The student chose {selected}: "{options.get(selected, "")}"
The correct answer is {correct}: "{options.get(correct, "")}"
Textbook explanation: {question.get("explanation", "")}

Classify the mistake as exactly one of:
- "conceptual": the student misunderstands the underlying idea, definition or law.
- "calculation": the idea was right but they slipped in arithmetic, units, signs or a formula step.
- "silly": they most likely knew it but misread the question, mixed up similar words, or picked carelessly.

Return ONLY this JSON:
{{"type": "conceptual" | "calculation" | "silly", "reason": "one short sentence (max 25 words) to the student saying what went wrong and what to revisit"}}"""


async def classify_with_gemini(question: dict, selected: str, correct: str, difficulty: str) -> Optional[dict]:
    """``{"type", "reason"}`` from Gemini, or None if it could not give a usable answer."""
    settings = get_settings()
    if not settings.quiz_llm_enabled or not is_task_configured("mistake_analysis"):
        return None
    try:
        # Route "mistake_analysis": Groq (small) -> OpenRouter -> Gemini.
        raw, provider = await asyncio.wait_for(
            acall_llm(
                "mistake_analysis",
                _prompt(question, selected, correct, difficulty),
                system=_SYSTEM,
                json_mode=True,
                max_tokens=1024,  # room for reasoning tokens plus the short JSON
            ),
            timeout=settings.quiz_llm_timeout_seconds,
        )
        parsed = gemini_service._extract_json_block(raw)
    except Exception as exc:  # quota, timeout, bad JSON on every provider: use the rule
        logger.warning("Mistake classification: AI unavailable (%s)", exc)
        return None
    if isinstance(parsed, list) and parsed:
        parsed = parsed[0]
    if not isinstance(parsed, dict):
        return None
    kind = str(parsed.get("type", "")).strip().lower()
    if kind not in KINDS:
        logger.warning("Mistake classification: Gemini returned unknown type %r", kind)
        return None
    reason = " ".join(str(parsed.get("reason", "")).split())[:240]
    logger.info("Mistake classified as %s by %s", kind, provider)
    return {"type": kind, "reason": reason, "provider": provider}
