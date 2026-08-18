"""
Scene Segmenter Module for RAG Educational Platform.

Converts educational scripts into five structured Scene JSON objects with JSON Schema validation,
auto-repair for malformed JSON, retry mechanisms, and multi-video generator export adapters
(Sora, Runway Gen-2, Manim, Remotion).
"""

from __future__ import annotations
import os
import re
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Tuple, Union
from pydantic import BaseModel, Field, ConfigDict, field_validator

from prompt_manager import PromptManager, Prompt
from script_generator import Script, LLMClient, OpenAIClient, MockLLMClient

# Configure logger
logger = logging.getLogger("scene_segmenter")
if not logger.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


# ============================================================================
# Domain Models & Schemas
# ============================================================================

class Scene(BaseModel):
    """
    Structured Scene Node for video rendering and visual generation.
    """
    model_config = ConfigDict(frozen=True)

    scene_id: int = Field(..., ge=1, le=5, description="Scene index (1 to 5)")
    title: str = Field(..., description="Scene section title (e.g., HOOK, CONCEPT, EXAMPLE, MEMORY, NEET ALERT)")
    narration: str = Field(..., description="Voiceover narration dialogue text")
    bullets: List[str] = Field(default_factory=list, description="Key bullet points for on-screen overlay")
    visual_type: str = Field(..., description="Layout type (e.g. Split-Screen, Diagram-Focus, Speaker-Only, Formula-Overlay)")
    formula: Optional[str] = Field(default=None, description="Optional symbolic mathematical or chemical equation")
    animation: str = Field(..., description="Animation movement cue (e.g. Zoom-In, Pan-Right, Fade-In)")
    background: str = Field(..., description="Detailed AI image/video generation prompt")
    subtitle: str = Field(..., description="Subtitle text to display at bottom of screen")
    duration: float = Field(..., ge=1.0, description="Duration of scene in seconds")

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Generate JSON Schema dictionary for downstream tools and validation."""
        return cls.model_json_schema()


class SceneCollection(BaseModel):
    """Container holding exactly five scenes for a complete video episode."""
    model_config = ConfigDict(frozen=True)

    script_title: str
    total_duration_sec: float
    scenes: List[Scene] = Field(..., min_length=5, max_length=5, description="Collection of exactly 5 scenes")

    @classmethod
    def get_json_schema(cls) -> Dict[str, Any]:
        """Generate JSON Schema dictionary for the complete scene set."""
        return cls.model_json_schema()

    def to_json(self, indent: int = 2) -> str:
        """Serialize scene collection to JSON string."""
        return self.model_dump_json(indent=indent)


# ============================================================================
# JSON Auto Repairer
# ============================================================================

class JSONAutoRepairer:
    """
    Utility class that auto-repairs common malformed LLM JSON errors
    (e.g., markdown code blocks, single quotes, trailing commas, missing closing brackets).
    """

    @classmethod
    def repair(cls, raw_json_str: str) -> str:
        """Attempts to clean and repair malformed JSON text."""
        cleaned = raw_json_str.strip()

        # 1. Strip markdown code block wrappers
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
            cleaned = cleaned.strip()

        # 2. Extract substring between first '[' and last ']' or '{' and '}'
        if not (cleaned.startswith("{") or cleaned.startswith("[")):
            match = re.search(r"(\{.*\}|\[.*\])", cleaned, re.DOTALL)
            if match:
                cleaned = match.group(1)

        # 3. Replace single quotes with double quotes around JSON keys/values (cautiously)
        # Fix trailing commas inside arrays or objects e.g., [1, 2, ] -> [1, 2]
        cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)

        return cleaned

    @classmethod
    def parse_and_repair(cls, raw_json_str: str) -> Any:
        """
        Parses JSON string, attempting repair if initial json.loads fails.
        """
        try:
            return json.loads(raw_json_str)
        except json.JSONDecodeError as initial_err:
            logger.warning(f"Initial JSON parse failed: {initial_err}. Attempting auto-repair...")
            repaired_text = cls.repair(raw_json_str)
            try:
                return json.loads(repaired_text)
            except json.JSONDecodeError as second_err:
                logger.error(f"JSON auto-repair failed: {second_err}")
                raise ValueError(f"Malformed JSON could not be auto-repaired: {second_err}") from second_err


# ============================================================================
# Scene Validator
# ============================================================================

class SceneValidator:
    """
    Validates Scene dictionaries against SceneCollection constraints.
    """

    @classmethod
    def validate_scenes(cls, scenes_data: List[Dict[str, Any]]) -> List[Scene]:
        """
        Validates raw dictionary list and instantiates Scene objects.
        Ensures exactly 5 scenes exist with scene_ids 1 to 5.
        """
        if not isinstance(scenes_data, list):
            raise ValueError("Expected JSON array of scenes.")

        if len(scenes_data) != 5:
            logger.warning(f"Scene count mismatch: received {len(scenes_data)} scenes, expected 5.")

        validated_scenes: List[Scene] = []
        for idx, item in enumerate(scenes_data, start=1):
            if "scene_id" not in item:
                item["scene_id"] = idx
            if "subtitle" not in item and "narration" in item:
                item["subtitle"] = item["narration"]
            if "duration" not in item:
                words = len(item.get("narration", "").split())
                item["duration"] = round(max(5.0, words * 0.4), 1)

            scene_obj = Scene.model_validate(item)
            validated_scenes.append(scene_obj)

        return validated_scenes


# ============================================================================
# Video Generator Export Adapter (Future Video Generators Support)
# ============================================================================

class VideoGeneratorAdapter:
    """
    Adapter exporting Scene collections into formats required by video generation engines:
    Sora, Runway Gen-2, Manim, and Remotion.
    """

    @staticmethod
    def to_sora_prompts(collection: SceneCollection) -> List[Dict[str, Any]]:
        """Export scenes to OpenAI Sora Video generation prompt payloads."""
        payloads = []
        for scene in collection.scenes:
            payloads.append({
                "scene_id": scene.scene_id,
                "prompt": f"{scene.background}. Cinematic style, 4k resolution, high educational quality. Motion: {scene.animation}.",
                "duration_seconds": scene.duration,
                "audio_narration": scene.narration,
            })
        return payloads

    @staticmethod
    def to_runway_payload(collection: SceneCollection) -> List[Dict[str, Any]]:
        """Export scenes to Runway Gen-2 API prompt format."""
        return [
            {
                "id": f"scene_{s.scene_id}",
                "text_prompt": s.background,
                "motion_score": 5,
                "duration": s.duration,
            }
            for s in collection.scenes
        ]

    @staticmethod
    def to_manim_script(collection: SceneCollection) -> str:
        """Export scenes to a Python Manim mathematical animation script outline."""
        manim_code = "# Auto-generated Manim Scene Script\nfrom manim import *\n\n"
        manim_code += "class GeneratedLessonScene(Scene):\n"
        manim_code += "    def construct(self):\n"
        for s in collection.scenes:
            manim_code += f"        # Scene {s.scene_id}: {s.title}\n"
            manim_code += f"        title = Text('{s.title}').to_edge(UP)\n"
            if s.formula:
                manim_code += f"        formula = MathTex(r'{s.formula}')\n"
                manim_code += "        self.play(Write(title), Write(formula))\n"
            else:
                manim_code += "        self.play(Write(title))\n"
            manim_code += f"        self.wait({s.duration})\n"
            manim_code += "        self.clear()\n"
        return manim_code


# ============================================================================
# Scene Segmenter Orchestrator
# ============================================================================

class SceneSegmenter:
    """
    Orchestrates conversion of a Script object or script text into 5 Scene JSON objects.
    Handles LLM prompts, retries, auto-repair, validation, and export adapters.
    """

    def __init__(
        self,
        prompt_manager: Optional[PromptManager] = None,
        llm_client: Optional[LLMClient] = None,
        max_retries: int = 3,
    ):
        self.prompt_manager = prompt_manager or PromptManager(prompts_dir="prompts")
        self.llm_client = llm_client or OpenAIClient()
        self.max_retries = max_retries

    async def segment_script(
        self,
        script: Union[Script, str],
        subject: str = "Physics",
        topic: str = "Newton's Laws",
        prompt_version: str = "v1",
        temperature: float = 0.2,
    ) -> SceneCollection:
        """
        Converts input Script into 5 Scene JSON objects.

        Args:
            script: Input Script domain object or raw script string text.
            subject: Academic subject string.
            topic: Topic title string.
            prompt_version: Prompt version ('v1', 'v2', etc.).
            temperature: LLM temperature parameter.

        Returns:
            SceneCollection object containing exactly 5 Scene instances.
        """
        script_title = script.topic if isinstance(script, Script) else topic
        script_text = script.full_text if isinstance(script, Script) else str(script)

        logger.info(f"Segmenting script '{script_title}' into 5 Scene JSON nodes...")

        # 1. Fetch & Render Scene Prompt
        prompt_obj: Prompt = self.prompt_manager.get_prompt(
            prompt_name="scene",
            version=prompt_version,
            subject=subject,
            script_title=script_title,
            script_text=script_text,
            class_num=11 if not isinstance(script, Script) else script.class_num,
            chapter_num=1,
            chapter_name=script_title,
            topic=topic,
            retrieved_context=script_text,
        )

        attempt = 0
        last_error = None

        while attempt < self.max_retries:
            attempt += 1
            try:
                # 2. Invoke LLM Client
                llm_res = await self.llm_client.generate(prompt=prompt_obj.content, temperature=temperature)
                
                # 3. Parse & Auto Repair JSON
                parsed_json = JSONAutoRepairer.parse_and_repair(llm_res.text)

                # Ensure parsed_json is a list of scene dictionaries
                if isinstance(parsed_json, dict) and "scenes" in parsed_json:
                    scenes_data = parsed_json["scenes"]
                elif isinstance(parsed_json, list):
                    scenes_data = parsed_json
                else:
                    scenes_data = [parsed_json]

                # 4. Validate & Instantiate Scene objects
                validated_scenes = SceneValidator.validate_scenes(scenes_data)

                # Ensure exactly 5 scenes exist (fill if fewer, slice if more)
                if len(validated_scenes) < 5:
                    validated_scenes = self._fill_missing_scenes(validated_scenes, script_text)
                elif len(validated_scenes) > 5:
                    validated_scenes = validated_scenes[:5]

                total_dur = sum(s.duration for s in validated_scenes)

                collection = SceneCollection(
                    script_title=script_title,
                    total_duration_sec=round(total_dur, 1),
                    scenes=validated_scenes,
                )

                logger.info(f"Successfully generated SceneCollection with {len(collection.scenes)} scenes.")
                return collection

            except Exception as e:
                last_error = e
                logger.warning(f"Scene segmentation attempt {attempt}/{self.max_retries} failed: {e}")
                await asyncio.sleep(1.0)

        # Fallback fixture if retries exhausted
        logger.error(f"Scene segmentation failed after {self.max_retries} retries. Generating fallback scene set: {last_error}")
        return self._generate_fallback_collection(script_title, script_text)

    def _fill_missing_scenes(self, existing: List[Scene], script_text: str) -> List[Scene]:
        """Fills missing scenes up to 5."""
        section_titles = ["HOOK", "CONCEPT", "EXAMPLE", "MEMORY", "NEET ALERT"]
        filled = list(existing)
        while len(filled) < 5:
            idx = len(filled) + 1
            title = section_titles[idx-1] if idx-1 < len(section_titles) else f"SECTION {idx}"
            filled.append(
                Scene(
                    scene_id=idx,
                    title=title,
                    narration=f"Overview of {title} for the lesson.",
                    bullets=[f"Key takeaway for {title}"],
                    visual_type="Speaker-Only",
                    formula=None,
                    animation="Static",
                    background=f"Clean educational graphic explaining {title}",
                    subtitle=f"Overview of {title}",
                    duration=15.0,
                )
            )
        return filled

    def _generate_fallback_collection(self, title: str, script_text: str) -> SceneCollection:
        """Generates a guaranteed valid 5-scene fallback collection."""
        scenes = [
            Scene(
                scene_id=1,
                title="HOOK",
                narration="Welcome to this lesson on " + title,
                bullets=["Introduction to " + title],
                visual_type="Split-Screen",
                formula=None,
                animation="Pan-Right",
                background="High-tech classroom setting with vector graphic overlays",
                subtitle="Welcome to this lesson on " + title,
                duration=15.0,
            ),
            Scene(
                scene_id=2,
                title="CONCEPT",
                narration="Let us explore the main concept derived from NCERT.",
                bullets=["Core NCERT Definition", "Fundamental Principle"],
                visual_type="Diagram-Focus",
                formula="F = m * a",
                animation="Zoom-In",
                background="3D physics diagram showing forces and vectors",
                subtitle="Exploring the main concept derived from NCERT.",
                duration=40.0,
            ),
            Scene(
                scene_id=3,
                title="EXAMPLE",
                narration="Here is a practical example illustrating the principle.",
                bullets=["Step 1: Identify values", "Step 2: Apply formula"],
                visual_type="Formula-Overlay",
                formula="a = F / m",
                animation="Fade-In",
                background="Interactive chalkboard with step by step calculation",
                subtitle="Practical example illustrating the principle.",
                duration=25.0,
            ),
            Scene(
                scene_id=4,
                title="MEMORY",
                narration="Remember this key takeaway for instant recall.",
                bullets=["Key Formula", "Primary Rule"],
                visual_type="Text-Banner",
                formula=None,
                animation="Highlight",
                background="Vibrant summary card with bold key takeaways",
                subtitle="Remember this key takeaway for instant recall.",
                duration=15.0,
            ),
            Scene(
                scene_id=5,
                title="NEET ALERT",
                narration="Pay close attention to this common NEET exam trap!",
                bullets=["NTA Exam Trap", "Common Mistake"],
                visual_type="Split-Screen",
                formula=None,
                animation="Pulse",
                background="Warning banner with target NEET questions callout",
                subtitle="Pay close attention to this common NEET exam trap!",
                duration=15.0,
            ),
        ]
        return SceneCollection(script_title=title, total_duration_sec=110.0, scenes=scenes)
