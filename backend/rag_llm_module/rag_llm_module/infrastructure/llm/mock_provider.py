from typing import Type, TypeVar, Optional, Dict, Any
from pydantic import BaseModel
from rag_llm_module.domain.entities.prompt import RenderedPrompt
from rag_llm_module.domain.interfaces.llm_provider import ILLMProvider
from rag_llm_module.domain.entities.script import EducationalScript, DialogueLine
from rag_llm_module.domain.entities.scene import SceneGraph, VisualSceneNode
from rag_llm_module.domain.entities.quiz import QuizSet, QuizQuestion, QuizChoice
from rag_llm_module.domain.entities.evaluation import HallucinationScore
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("infrastructure.llm.mock_provider")

T = TypeVar("T", bound=BaseModel)


class MockLLMProvider(ILLMProvider):
    """
    Mock implementation of ILLMProvider.
    Returns deterministic, schema-compliant domain objects for unit tests without network calls.
    """

    def __init__(self, default_response_map: Optional[Dict[Type[BaseModel], BaseModel]] = None):
        self.default_response_map = default_response_map or {}

    async def generate_structured(
        self,
        prompt: RenderedPrompt,
        response_schema: Type[T],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> T:
        logger.info(f"[MockLLMProvider] Invoked for schema '{response_schema.__name__}' using template '{prompt.template_name}'")

        if response_schema in self.default_response_map:
            return self.default_response_map[response_schema]  # type: ignore

        # Default fallbacks based on target domain model schema
        if response_schema == EducationalScript:
            return EducationalScript(
                title="Understanding Newton's Laws",
                summary="An introductory dialogue explaining the fundamental concepts of forces and motion.",
                target_grade=11,
                dialogue=[
                    DialogueLine(
                        speaker="Teacher",
                        dialogue="Welcome class! Today we explore Newton's First Law of Motion, also known as Inertia.",
                        emotion_tone="Enthusiastic",
                        visual_cue="Teacher points to a stationary wooden block resting on a smooth surface.",
                    ),
                    DialogueLine(
                        speaker="Student",
                        dialogue="Does that mean an object won't move unless an external force acts on it?",
                        emotion_tone="Curious",
                        visual_cue="Student raises hand thoughtfully.",
                    ),
                    DialogueLine(
                        speaker="Teacher",
                        dialogue="Exactly! An object at rest stays at rest, and an object in motion continues moving at constant velocity unless acted upon by a net force.",
                        emotion_tone="Explanatory",
                        visual_cue="Animated force vector arrows appear around the block.",
                    ),
                ],
                key_learning_points=[
                    "Inertia is the resistance of any physical object to any change in its velocity.",
                    "An unbalanced net external force is required to change motion.",
                ],
                estimated_duration_sec=90.0,
            )  # type: ignore

        elif response_schema == SceneGraph:
            return SceneGraph(
                script_title="Understanding Newton's Laws",
                total_duration_sec=90.0,
                scenes=[
                    VisualSceneNode(
                        scene_id=1,
                        timestamp_start_sec=0.0,
                        timestamp_end_sec=30.0,
                        layout_type="Split-Screen",
                        on_screen_text="Newton's First Law: Law of Inertia",
                        background_asset_prompt="Modern 3D physics laboratory with clean lighting and vector graphs",
                        spoken_dialogue_ref="Welcome class! Today we explore Newton's First Law...",
                        camera_movement="Pan-Right",
                    ),
                    VisualSceneNode(
                        scene_id=2,
                        timestamp_start_sec=30.0,
                        timestamp_end_sec=90.0,
                        layout_type="Diagram-Focus",
                        on_screen_text="Net Force = 0 => Constant Velocity",
                        background_asset_prompt="Interactive diagram showing balanced vs unbalanced force arrows on a moving cart",
                        spoken_dialogue_ref="An object at rest stays at rest...",
                        camera_movement="Zoom-In",
                    ),
                ],
            )  # type: ignore

        elif response_schema == QuizSet:
            return QuizSet(
                subject="Physics",
                topic="Newton's Laws",
                class_num=11,
                questions=[
                    QuizQuestion(
                        question_id=1,
                        question_type="multiple_choice",
                        blooms_taxonomy_level="Understand",
                        prompt_text="What property of an object quantifies its inertia?",
                        choices=[
                            QuizChoice(option_id="A", text="Velocity"),
                            QuizChoice(option_id="B", text="Mass"),
                            QuizChoice(option_id="C", text="Acceleration"),
                            QuizChoice(option_id="D", text="Friction"),
                        ],
                        correct_option_id="B",
                        explanation="Mass is the quantitative measure of inertia. A heavier body resists changes in velocity more than a lighter body.",
                    )
                ],
            )  # type: ignore

        elif response_schema == HallucinationScore:
            return HallucinationScore(
                is_faithful=True,
                faithfulness_score=0.95,
                supported_claims=["Newton's First Law describes inertia."],
                unsupported_claims=[],
            )  # type: ignore

        # Fallback empty model instantiation if fields allow defaults
        try:
            return response_schema()  # type: ignore
        except Exception as e:
            raise ValueError(f"MockLLMProvider does not have a default fixture for schema {response_schema}: {e}")

    async def generate_text(
        self,
        prompt: RenderedPrompt,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        return f"Mock response for template '{prompt.template_name}:{prompt.template_version}'"
