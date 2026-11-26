import asyncio
import json
import random
import logging
import re
import time
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import get_settings
from app.llm.llm_router import AllProvidersFailedError, LLMRequestError, acall_llm, is_task_configured

logger = logging.getLogger("textbook_assistant.gemini")


class GeminiUnavailable(RuntimeError):
    """Gemini could not be reached, or was too busy to answer.

    Separate from a configuration or request error on purpose: an overloaded
    model is a temporary condition the caller can work around, while a missing
    key or a malformed prompt is not.

    ``status`` says why, so the logs can tell the cases apart:
    ``"unavailable"`` (overloaded or down, HTTP 5xx), ``"exhausted"`` (quota or
    rate limit, HTTP 429) or ``"network"`` (could not reach Google at all).
    """

    def __init__(self, message: str, status: str = "unavailable", http_status: Optional[int] = None) -> None:
        super().__init__(message)
        self.status = status
        self.http_status = http_status


def describe_gemini_failure(exc: BaseException) -> str:
    """One readable phrase for the log: is Gemini unavailable, exhausted or in error?"""
    if isinstance(exc, asyncio.TimeoutError):
        return "UNAVAILABLE - no answer within the time limit"
    if isinstance(exc, AllProvidersFailedError):
        return "UNAVAILABLE - every AI provider failed (" + "; ".join(f"{n}: {w}" for n, w in exc.failures) + ")"
    if isinstance(exc, LLMRequestError):
        return f"ERROR - {exc}"
    if isinstance(exc, GeminiUnavailable):
        http = f" (HTTP {exc.http_status})" if exc.http_status else ""
        if exc.status == "exhausted":
            return f"EXHAUSTED - quota or rate limit reached{http}"
        if exc.status == "network":
            return "UNREACHABLE - could not connect to Google"
        return f"UNAVAILABLE - the model is overloaded or down{http}"
    return f"ERROR - {_short(str(exc))}"


def _short(detail: str, limit: int = 140) -> str:
    """The message out of a Google JSON error body, or the first part of the text."""
    try:
        message = json.loads(detail).get("error", {}).get("message")
        if message:
            detail = message
    except (ValueError, AttributeError):
        pass
    detail = " ".join(str(detail).split())
    return detail if len(detail) <= limit else detail[:limit].rstrip() + "..."


# Statuses worth trying again. 429 is the quota/rate limit, 503 is the
# "model is overloaded" the API returns under load; the 5xx family is transient
# by definition. Anything else (400 bad request, 403 bad key) will fail the same
# way on every attempt, so it is raised immediately.
_RETRY_STATUS = {429, 500, 502, 503, 504}
_MAX_ATTEMPTS = 4
_BASE_BACKOFF_SECONDS = 1.5


# The model is asked for NEET_ALERT but reliably shortens it. An unknown part
# name silently falls back to the CONCEPT theme and drops out of the flow strip,
# so the aliases are normalised before the scene reaches the renderer.
_PART_ALIASES = {
    "ALERT": "NEET_ALERT",
    "NEET": "NEET_ALERT",
    "EXAM_ALERT": "NEET_ALERT",
    "NEET_TRAP": "NEET_ALERT",
    "RECALL": "MEMORY",
    "INTRO": "HOOK",
}

# Scene plan per video length. Narration is spoken at about 150 words a
# minute (budgets tuned on test renders: models write ~10% short), so the word budget (narration only) sets the running time; the intro
# and outro slides add a few seconds on top.
LENGTH_PLANS = {
    30: {"parts": ["HOOK", "CONCEPT", "NEET_ALERT"], "words": 50},
    60: {"parts": ["HOOK", "CONCEPT", "EXAMPLE", "MEMORY", "NEET_ALERT"], "words": 135},
    120: {"parts": ["HOOK", "CONCEPT", "EXAMPLE", "MEMORY", "NEET_ALERT"], "words": 300},
    300: {"parts": ["HOOK", "CONCEPT", "CONCEPT", "EXAMPLE", "CONCEPT", "EXAMPLE", "MEMORY", "NEET_ALERT"],
          "words": 720},
}
_PART_PURPOSE = {
    "HOOK": "Everyday curiosity or intuition hook.",
    "CONCEPT": "Core textbook definition, principle, and mathematical formula.",
    "EXAMPLE": "Real-world example or numerical step.",
    "MEMORY": "Mnemonic or key memory rule.",
    "NEET_ALERT": "High-yield exam trap or important condition.",
}


def length_plan(target_seconds: Optional[int]) -> dict:
    """The scene plan for the nearest supported length (default 1 minute)."""
    if not target_seconds:
        return LENGTH_PLANS[60]
    nearest = min(LENGTH_PLANS, key=lambda k: abs(k - int(target_seconds)))
    return LENGTH_PLANS[nearest]


# Per-part fallback when the model omits visual_type. Deliberately not "alert"
# for every part: that is what made five scenes render the same hazard triangle.
_DEFAULT_VISUAL = {
    "HOOK": "topic_card",
    "CONCEPT": "process",
    "EXAMPLE": "formula",
    "MEMORY": "comparison",
    "NEET_ALERT": "alert",
}


class GeminiLLMService:
    """Google Gemini LLM service for textbook grounded script, scene, and answer generation."""

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"

    @property
    def api_key(self) -> str:
        return self.settings.gemini_api_key

    @property
    def model(self) -> str:
        return self.settings.llm_model or "gemini-3.6-flash"

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and len(self.api_key.strip()) > 10)

    async def _backoff(self, attempt: int, retry_after: Optional[str], detail: str) -> None:
        """Wait before retrying, honouring Retry-After when the API sends one."""
        delay = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except ValueError:
                pass
        # Jitter, so several queued jobs do not all retry on the same tick.
        delay += random.uniform(0, 0.5)
        logger.warning(
            "Gemini is not answering (attempt %s/%s), retrying in %.1fs: %s",
            attempt, _MAX_ATTEMPTS, delay, _short(detail),
        )
        await asyncio.sleep(delay)

    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: Optional[int] = None,
        task: str = "doubt_answer",
        json_mode: bool = False,
    ) -> str:
        """Kept for older callers: one AI answer through the multi-provider router.

        The retry-and-backoff loop that used to live here is gone; the router
        tries each provider once and moves on (see app/llm/llm_router.py).
        """
        text, _ = await acall_llm(
            task, prompt, system=system_instruction, json_mode=json_mode,
            max_tokens=max_output_tokens or self.settings.llm_max_output_tokens,
        )
        return text

    def _extract_json_block(self, raw_text: str) -> Any:
        """Extract and parse JSON array or object from markdown or raw text."""
        cleaned = raw_text.strip()
        
        # Remove ```json ... ```
        if "```" in cleaned:
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        # If surrounding characters exist
        match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.DOTALL)
        if match:
            cleaned = match.group(1)

        # Fix trailing commas
        cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)

        return json.loads(cleaned)

    async def generate_educational_scenes(
        self,
        topic: str,
        subject: Optional[str] = "Physics",
        class_level: Optional[str] = "11",
        retrieved_context: Optional[str] = "",
        target_seconds: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Generate grounded educational scenes for video assembly (any provider)."""
        scenes, _ = await self.generate_educational_scenes_with_provider(
            topic, subject, class_level, retrieved_context, target_seconds)
        return scenes

    async def generate_educational_scenes_with_provider(
        self,
        topic: str,
        subject: Optional[str] = "Physics",
        class_level: Optional[str] = "11",
        retrieved_context: Optional[str] = "",
        target_seconds: Optional[int] = None,
    ) -> tuple:
        """``(scenes, provider)``: the scene script and which AI provider wrote it.

        ``target_seconds`` (30, 60, 120 or 300) sets how many scenes there are and
        how many words of narration they carry, which is what sets the length.

        Raises AllProvidersFailedError when no provider could answer.
        """
        if not is_task_configured("video_script"):
            error_msg = "No AI API key is configured (GEMINI_API_KEY, GROQ_API_KEY or OPENROUTER_API_KEY). Cannot generate educational video scenes."
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        plan = length_plan(target_seconds)
        parts = plan["parts"]
        n_scenes = len(parts)
        total_words = plan["words"]
        per_scene = max(15, round(total_words / n_scenes))
        seconds = int(target_seconds or 60)
        structure = "\n".join(f"{i}. {p.replace('_', ' ')}: {_PART_PURPOSE[p]}" for i, p in enumerate(parts, 1))

        system_instruction = (
            f"You are a master STEM educator and video script director for Class {class_level or '11'} {subject or 'Physics'}. "
            f"You convert textbook context into structured JSON scenes for a {seconds}-second educational microlearning video. "
            "CRITICAL RULES: Ground everything strictly in the provided textbook context. Do NOT invent unsupported facts. "
            f'Output ONLY a JSON object of the form {{"scenes": [ ...exactly {n_scenes} scene objects... ]}}.'
        )

        prompt = f"""
Convert the following textbook context and topic into a {n_scenes}-scene educational video script.

TOPIC: {topic}
SUBJECT: {subject or 'Physics'}
CLASS LEVEL: Class {class_level or '11'}

GROUNDED TEXTBOOK CONTEXT:
{retrieved_context if retrieved_context else "Use core curriculum principles for " + topic}

TARGET LENGTH: about {seconds} seconds. Narration is spoken at about 150 words
per minute, so write {total_words} words of "narration_text" IN TOTAL (count them: models
usually write too few), roughly {per_scene} words per scene. Set "duration_hint_seconds" to about the
time its narration takes to read. Do not pad or rush: the length matters.

SCENE STRUCTURE REQUIRED (exactly {n_scenes} scenes, in this order, using these "part" values):
{structure}

The example below shows one scene of each type; produce the {n_scenes} scenes listed above.

SCHEMA REQUIRED (Return {{"scenes": [ ...a list of {n_scenes} objects... ]}}):

Each scene has a "visual_type" that decides what is drawn in the right-hand
panel, and a "visual_data" that supplies its content. A panel with no content is
worse than no panel, so never emit a visual_type without the matching
visual_data. Give the scenes DIFFERENT visual types — repeating one type
across the video makes every slide look identical.

  topic_card   {{"kicker": "SOURCED FROM", "chapter": "...", "scope": "Class 11 - Physics"}}
  process      {{"steps": ["Short step", "Short step", "Short step"]}}
  comparison   {{"left": {{"title": "g", "points": ["...", "..."]}},
                "right": {{"title": "G", "points": ["...", "..."]}}}}
  diagram      {{"title": "...", "labels": ["Term", "Term", "Term"]}}
  checklist    {{"title": "REVISE THESE", "items": ["Term", "Term", "Term"]}}
  formula      {{"title": "..."}} plus a top-level "formula_latex"
  alert        {{"caption": "The trap, in a few words"}}

Rules that matter:
- "slide_bullets": at most 3, each under 110 characters, each able to stand
  alone. Never open a bullet with "However", "This" or "It".
- "definition" on the CONCEPT scene must be the textbook's own wording, with
  "definition_source" naming the chapter it came from. Leave both out rather
  than paraphrasing.
- "visual_data" labels and items are short TERMS (1-3 words), not sentences.
- "narration_text" is spoken aloud, so no symbols or markup.
- Use "alert" for the NEET_ALERT scene only.

[
  {{
    "part": "HOOK",
    "slide_title": "Short Slide Headline (max 6 words)",
    "slide_bullets": ["Key bullet point 1", "Key bullet point 2"],
    "narration_text": "About {per_scene} words of natural spoken sentences introducing the topic.",
    "visual_type": "topic_card",
    "visual_data": {{"kicker": "SOURCED FROM", "chapter": "Chapter name", "scope": "Class {class_level or '11'} - {subject or 'Physics'}"}},
    "animation_type": "fade_in",
    "duration_hint_seconds": 12
  }},
  {{
    "part": "CONCEPT",
    "slide_title": "Concept Headline",
    "definition": "The textbook's exact defining sentence.",
    "definition_source": "Class {class_level or '11'} {subject or 'Physics'}, Ch.N Chapter Name",
    "slide_bullets": ["Bullet 1", "Bullet 2"],
    "narration_text": "Narration explaining the core principle clearly.",
    "visual_type": "process",
    "visual_data": {{"steps": ["First step", "Second step", "Third step"]}},
    "animation_type": "slide_left",
    "duration_hint_seconds": 18
  }},
  {{
    "part": "EXAMPLE",
    "slide_title": "Example Headline",
    "slide_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
    "narration_text": "Narration walking through the example.",
    "visual_type": "formula",
    "formula_latex": "F = G m_1 m_2 / r^2",
    "visual_data": {{"title": "Chapter name"}},
    "animation_type": "zoom",
    "duration_hint_seconds": 16
  }},
  {{
    "part": "MEMORY",
    "slide_title": "Memory Rule",
    "slide_bullets": ["Bullet 1", "Bullet 2"],
    "narration_text": "Narration with the mnemonic and memory aid.",
    "visual_type": "comparison",
    "visual_data": {{"left": {{"title": "Term A", "points": ["Point", "Point"]}}, "right": {{"title": "Term B", "points": ["Point", "Point"]}}}},
    "animation_type": "slide_left",
    "duration_hint_seconds": 14
  }},
  {{
    "part": "NEET_ALERT",
    "slide_title": "Exam Alert",
    "slide_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
    "narration_text": "Narration highlighting the exam trap.",
    "visual_type": "alert",
    "visual_data": {{"caption": "The trap in a few words"}},
    "animation_type": "zoom",
    "duration_hint_seconds": 14
  }}
]

Output ONLY the JSON object {{"scenes": [...]}} without any markdown wrappers or commentary.
"""

        try:
            logger.info(f"Generating educational scenes for '{topic}' (route: video_script)...")
            raw_response, provider = await acall_llm(
                "video_script", prompt, system=system_instruction, json_mode=True,
                max_tokens=self.settings.llm_max_output_tokens,
            )
            scenes = self._extract_json_block(raw_response)
            if isinstance(scenes, dict):
                scenes = scenes.get("scenes") or next((v for v in scenes.values() if isinstance(v, list)), None)

            if isinstance(scenes, list) and len(scenes) >= 3:
                # Sanitize and validate required keys
                validated_scenes = []
                for s in scenes:
                    part = _PART_ALIASES.get(
                        str(s.get("part", "CONCEPT")).upper().replace(" ", "_"),
                        str(s.get("part", "CONCEPT")).upper().replace(" ", "_"),
                    )
                    # The renderer keys its theme, flow strip and panel off these
                    # fields. Dropping visual_data leaves every panel to draw its
                    # empty default, which is how five different scenes end up
                    # looking like the same slide; defaulting visual_type to
                    # "alert" does the same thing on purpose.
                    validated_scenes.append({
                        "part": part,
                        "slide_title": str(s.get("slide_title", topic)),
                        "definition": str(s.get("definition", "") or ""),
                        "definition_source": str(s.get("definition_source", "") or ""),
                        "slide_bullets": [str(b) for b in s.get("slide_bullets", []) if str(b).strip()],
                        "narration_text": str(s.get("narration_text", "")),
                        "visual_type": str(s.get("visual_type") or _DEFAULT_VISUAL.get(part, "checklist")),
                        "visual_data": s.get("visual_data") or {},
                        "formula_latex": s.get("formula_latex"),
                        "animation_type": str(s.get("animation_type", "fade_in")),
                        "duration_hint_seconds": s.get("duration_hint_seconds"),
                    })
                logger.info(f"Successfully generated {len(validated_scenes)} scenes for '{topic}' with {provider}")
                return validated_scenes, provider
            else:
                error_msg = f"{provider} returned invalid or empty scene structure: {str(scenes)[:300]}"
                logger.error(error_msg)
                raise ValueError(error_msg)

        except Exception as exc:
            logger.error(f"Scene generation failed for '{topic}': {exc}")
            raise

    async def answer_question(
        self,
        query: str,
        retrieved_context: str,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
    ) -> str:
        """Answer a student's question grounded in the retrieved textbook chunks."""
        if not is_task_configured("doubt_answer"):
            error_msg = "No AI API key is configured (GEMINI_API_KEY, OPENROUTER_API_KEY or GROQ_API_KEY). Cannot generate explanation."
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        system_instruction = (
            f"You are a knowledgeable, supportive NCERT textbook assistant for Class {class_level or '11'} {subject or 'Science'}. "
            "Explain concepts accurately, clearly, and concisely based strictly on the provided textbook context. "
            "If the context does not contain enough info, state clearly what the textbook covers."
        )

        prompt = f"""
STUDENT QUESTION: {query}

GROUNDED TEXTBOOK CONTEXT:
{retrieved_context}

Please provide a clear, well-structured, curriculum-accurate explanation answering the student's question.
"""
        text, _ = await acall_llm("doubt_answer", prompt, system=system_instruction, max_tokens=2048)
        return text


gemini_service = GeminiLLMService()
