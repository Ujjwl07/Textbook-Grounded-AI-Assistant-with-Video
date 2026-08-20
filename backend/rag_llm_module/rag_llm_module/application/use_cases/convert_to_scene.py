from typing import Optional
from rag_llm_module.domain.entities.script import EducationalScript
from rag_llm_module.domain.entities.scene import SceneGraph
from rag_llm_module.domain.interfaces.llm_provider import ILLMProvider
from rag_llm_module.application.services.prompt_manager import PromptManagerService
from rag_llm_module.application.services.cache_service import CacheService
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("application.use_cases.convert_to_scene")


class ConvertToSceneUseCase:
    """
    Use Case 2: Converts an EducationalScript into a time-coded SceneGraph with visual cues & prompts.
    """

    def __init__(
        self,
        prompt_manager: PromptManagerService,
        llm_provider: ILLMProvider,
        cache_service: CacheService,
    ):
        self.prompt_manager = prompt_manager
        self.llm_provider = llm_provider
        self.cache_service = cache_service

    async def execute(
        self,
        script: EducationalScript,
        version: Optional[str] = None,
        temperature: float = 0.2,
        bypass_cache: bool = False,
    ) -> SceneGraph:
        logger.info(f"Executing ConvertToSceneUseCase for script title: '{script.title}'")

        script_text_full = "\n".join([f"{d.speaker}: {d.dialogue} [{d.visual_cue}]" for d in script.dialogue])
        template_vars = {
            "script_title": script.title,
            "script_text": script_text_full,
        }

        prompt = self.prompt_manager.prepare_prompt(
            template_name="scene_conversion",
            version=version,
            variables=template_vars,
        )

        cache_key = self.cache_service.generate_cache_key(
            prompt=prompt,
            schema=SceneGraph,
            temperature=temperature,
        )

        if not bypass_cache:
            cached_scene = await self.cache_service.get_cached_structured(cache_key, SceneGraph)
            if cached_scene:
                return cached_scene

        scene_graph: SceneGraph = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=SceneGraph,
            temperature=temperature,
        )

        await self.cache_service.set_cached_structured(cache_key, scene_graph)
        return scene_graph
