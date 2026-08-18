from typing import Optional
from rag_llm_module.domain.entities.retrieval import RetrieverPayload
from rag_llm_module.domain.entities.script import EducationalScript
from rag_llm_module.domain.interfaces.llm_provider import ILLMProvider
from rag_llm_module.application.services.prompt_manager import PromptManagerService
from rag_llm_module.application.services.cache_service import CacheService
from rag_llm_module.application.services.hallucination import HallucinationDetectorService
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("application.use_cases.generate_script")


class GenerateScriptUseCase:
    """
    Use Case 1: Transforms retrieved context payload into an Educational Script.
    """

    def __init__(
        self,
        prompt_manager: PromptManagerService,
        llm_provider: ILLMProvider,
        cache_service: CacheService,
        hallucination_detector: HallucinationDetectorService,
    ):
        self.prompt_manager = prompt_manager
        self.llm_provider = llm_provider
        self.cache_service = cache_service
        self.hallucination_detector = hallucination_detector

    async def execute(
        self,
        payload: RetrieverPayload,
        version: Optional[str] = None,
        temperature: float = 0.2,
        bypass_cache: bool = False,
    ) -> EducationalScript:
        logger.info(f"Executing GenerateScriptUseCase for Subject: {payload.subject}, Topic: {payload.topic}")

        # 1. Prepare Rendered Prompt
        template_vars = payload.to_template_vars()
        prompt = self.prompt_manager.prepare_prompt(
            template_name="script_generation",
            version=version,
            variables=template_vars,
        )

        # 2. Check Cache
        cache_key = self.cache_service.generate_cache_key(
            prompt=prompt,
            schema=EducationalScript,
            temperature=temperature,
        )

        if not bypass_cache:
            cached_script = await self.cache_service.get_cached_structured(cache_key, EducationalScript)
            if cached_script:
                return cached_script

        # 3. LLM Completion
        script: EducationalScript = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=EducationalScript,
            temperature=temperature,
        )

        # 4. Verify Hallucinations
        script_text_for_audit = " ".join([d.dialogue for d in script.dialogue])
        await self.hallucination_detector.verify_and_enforce(
            context=payload.retrieved_context,
            generated_text=script_text_for_audit,
            raise_on_violation=False,
        )

        # 5. Store in Cache
        await self.cache_service.set_cached_structured(cache_key, script)

        return script
