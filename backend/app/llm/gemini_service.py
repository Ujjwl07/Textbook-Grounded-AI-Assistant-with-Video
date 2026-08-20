import json
import logging
import re
from typing import Any, Dict, List, Optional
import httpx

from app.core.config import get_settings

logger = logging.getLogger("textbook_assistant.gemini")


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

    async def generate_text(
        self,
        prompt: str,
        system_instruction: Optional[str] = None,
        temperature: float = 0.2,
        max_output_tokens: int = 2048,
    ) -> str:
        """Call Gemini API to generate plain text or structured response."""
        if not self.is_configured:
            raise RuntimeError("GEMINI_API_KEY is not configured in .env")

        endpoint = f"{self.base_url}/{self.model}:generateContent?key={self.api_key}"

        payload: Dict[str, Any] = {
            "contents": [
                {
                    "parts": [{"text": prompt}]
                }
            ],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }

        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(endpoint, json=payload)
            if response.status_code != 200:
                logger.error(f"Gemini API error ({response.status_code}): {response.text}")
                raise RuntimeError(f"Gemini API error {response.status_code}: {response.text[:200]}")

            data = response.json()
            candidates = data.get("candidates", [])
            if not candidates:
                raise RuntimeError("Gemini returned empty candidates list")

            parts = candidates[0].get("content", {}).get("parts", [])
            if not parts:
                raise RuntimeError("Gemini returned no content parts")

            return parts[0].get("text", "").strip()

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
    ) -> List[Dict[str, Any]]:
        """
        Generate grounded educational scenes for video assembly using Gemini LLM.
        
        Raises explicit RuntimeError if Gemini is unconfigured or fails.
        """
        if not self.is_configured:
            error_msg = "GEMINI_API_KEY is not configured in .env. Cannot generate educational video scenes without API key."
            logger.error(error_msg)
            raise RuntimeError(error_msg)

        system_instruction = (
            f"You are a master STEM educator and video script director for Class {class_level or '11'} {subject or 'Physics'}. "
            "You convert textbook context into structured JSON scenes for 60-90 second educational microlearning videos. "
            "CRITICAL RULES: Ground everything strictly in the provided textbook context. Do NOT invent unsupported facts. "
            "Output ONLY a raw JSON array of exactly 5 scene objects."
        )

        prompt = f"""
Convert the following textbook context and topic into a 5-scene educational video script.

TOPIC: {topic}
SUBJECT: {subject or 'Physics'}
CLASS LEVEL: Class {class_level or '11'}

GROUNDED TEXTBOOK CONTEXT:
{retrieved_context if retrieved_context else "Use core curriculum principles for " + topic}

SCENE STRUCTURE REQUIRED (exactly 5 scenes):
1. HOOK: Everyday curiosity or intuition hook.
2. CONCEPT: Core textbook definition, principle, and mathematical formula.
3. EXAMPLE: Real-world example or numerical step.
4. MEMORY: Mnemonic or key memory rule.
5. NEET ALERT: High-yield exam trap or important condition.

SCHEMA REQUIRED (Return a JSON list of 5 objects):
[
  {{
    "part": "HOOK",
    "slide_title": "Short Slide Headline (max 6 words)",
    "slide_bullets": ["Key bullet point 1", "Key bullet point 2", "Key bullet point 3"],
    "narration_text": "2 to 3 natural spoken sentences for voiceover narration explaining this scene.",
    "visual_type": "alert",
    "animation_type": "fade_in"
  }},
  {{
    "part": "CONCEPT",
    "slide_title": "Concept Headline",
    "slide_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
    "narration_text": "Narration text explaining the core principle clearly.",
    "visual_type": "formula",
    "formula_latex": "\\\\vec{{F}} = m\\\\vec{{a}}",
    "animation_type": "zoom"
  }},
  {{
    "part": "EXAMPLE",
    "slide_title": "Example Headline",
    "slide_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
    "narration_text": "Narration text walking through the example.",
    "visual_type": "alert",
    "animation_type": "slide_left"
  }},
  {{
    "part": "MEMORY",
    "slide_title": "Memory Rule",
    "slide_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
    "narration_text": "Narration text with mnemonic and memory aid.",
    "visual_type": "alert",
    "animation_type": "fade_in"
  }},
  {{
    "part": "ALERT",
    "slide_title": "Exam Alert",
    "slide_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
    "narration_text": "Narration text highlighting the exam trap.",
    "visual_type": "alert",
    "animation_type": "zoom"
  }}
]

Output ONLY the valid JSON array without any markdown wrappers or commentary.
"""

        try:
            logger.info(f"Generating educational scenes with Gemini ({self.model}) for '{topic}'...")
            raw_response = await self.generate_text(prompt, system_instruction=system_instruction, temperature=0.2)
            scenes = self._extract_json_block(raw_response)

            if isinstance(scenes, list) and len(scenes) >= 3:
                # Sanitize and validate required keys
                validated_scenes = []
                for s in scenes:
                    validated_scenes.append({
                        "part": str(s.get("part", "CONCEPT")).upper(),
                        "slide_title": str(s.get("slide_title", topic)),
                        "slide_bullets": list(s.get("slide_bullets", ["Key Concept"])),
                        "narration_text": str(s.get("narration_text", "")),
                        "visual_type": str(s.get("visual_type", "alert")),
                        "formula_latex": s.get("formula_latex"),
                        "animation_type": str(s.get("animation_type", "fade_in")),
                    })
                logger.info(f"Successfully generated {len(validated_scenes)} Gemini scenes for '{topic}'")
                return validated_scenes
            else:
                error_msg = f"Gemini returned invalid or empty scene structure: {scenes}"
                logger.error(error_msg)
                raise ValueError(error_msg)

        except Exception as exc:
            logger.error(f"Gemini scene generation failed for '{topic}': {exc}")
            raise

    async def answer_question(
        self,
        query: str,
        retrieved_context: str,
        subject: Optional[str] = None,
        class_level: Optional[str] = None,
    ) -> str:
        """Answer a student's question grounded in the retrieved textbook chunks."""
        if not self.is_configured:
            error_msg = "GEMINI_API_KEY is not configured in .env. Cannot generate explanation without API key."
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
        return await self.generate_text(prompt, system_instruction=system_instruction, temperature=0.3)


gemini_service = GeminiLLMService()
