"""Checks applied to LLM-written questions before a student sees them.

A model can return a well-formed question whose answer is not in the textbook,
or whose "correct" option is not among the options. Nothing here trusts the
model: a question that fails any check is dropped, and the rule-based generator
covers the gap.
"""

from __future__ import annotations

import random
import re
from typing import Any, List, Optional

from app.quiz.rule_based import LETTERS, Question

DIFFICULTIES = ("EASY", "MEDIUM", "HARD")

# A quote counts as grounded when this share of its word trigrams occur in the
# retrieved text. Below 1.0 on purpose: extraction leaves stray spaces and
# symbols that a model quietly tidies when it copies a sentence.
GROUNDING_THRESHOLD = 0.8
MIN_QUOTE_WORDS = 6

# The student cannot see the passage the model was shown.
_REFERS_TO_PASSAGE = re.compile(
    r"\b(the (?:given |above |following )?(?:passage|text|context|excerpt|paragraph)|"
    r"according to the (?:passage|text|context)|as mentioned above|in the above)\b",
    re.I,
)


def normalise_difficulty(value: Any) -> Optional[str]:
    text = str(value or "").strip().upper()
    return text if text in DIFFICULTIES else None


def _words(text: str) -> List[str]:
    return re.findall(r"[a-z0-9]+", str(text).lower())


def _trigrams(words: List[str]) -> set:
    return {tuple(words[i:i + 3]) for i in range(len(words) - 2)}


def quote_is_grounded(quote: str, context: str, threshold: float = GROUNDING_THRESHOLD) -> bool:
    """True when ``quote`` is (nearly) a verbatim run of ``context``."""
    words = _words(quote)
    if len(words) < MIN_QUOTE_WORDS:
        return False
    grams = _trigrams(words)
    if not grams:
        return False
    return len(grams & _trigrams(_words(context))) / len(grams) >= threshold


def _options_list(raw: Any) -> Optional[List[str]]:
    """Options as four strings in A-D order, from a dict or a list."""
    if isinstance(raw, dict):
        try:
            return [str(raw[letter]).strip() for letter in LETTERS]
        except KeyError:
            return None
    if isinstance(raw, list) and len(raw) == 4:
        return [str(item).strip() for item in raw]
    return None


def validate_item(item: Any, context: str, rng: random.Random) -> Optional[Question]:
    """A ``Question`` built from one model item, or None if it fails any check."""
    if not isinstance(item, dict):
        return None

    stem = str(item.get("question", "")).strip()
    options = _options_list(item.get("options"))
    correct = str(item.get("correct_option", item.get("correct_answer", ""))).strip().upper()
    explanation = str(item.get("explanation", "")).strip()
    quote = str(item.get("source_quote", "")).strip()
    difficulty = normalise_difficulty(item.get("difficulty")) or "MEDIUM"

    if len(stem) < 15 or not options or correct not in LETTERS or not explanation:
        return None
    if any(not option for option in options):
        return None
    if len({option.lower() for option in options}) != 4:
        return None
    if _REFERS_TO_PASSAGE.search(stem):
        return None
    if not quote_is_grounded(quote, context):
        return None

    answer_text = options[LETTERS.index(correct)]
    shuffled = options[:]
    rng.shuffle(shuffled)  # models favour B and C; the position carries no hint
    return Question(
        question=stem,
        options=shuffled,
        correct_index=shuffled.index(answer_text),
        difficulty=difficulty,
        explanation=explanation,
        source_quote=quote,
        citation="",
        kind="llm",
        source="gemini",
    )
