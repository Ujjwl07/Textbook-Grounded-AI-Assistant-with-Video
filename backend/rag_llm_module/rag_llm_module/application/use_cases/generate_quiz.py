from typing import Optional
from rag_llm_module.domain.entities.retrieval import RetrieverPayload
from rag_llm_module.domain.entities.quiz import QuizSet
from rag_llm_module.domain.interfaces.llm_provider import ILLMProvider
from rag_llm_module.application.services.prompt_manager import PromptManagerService
from rag_llm_module.application.services.cache_service import CacheService
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("application.use_cases.generate_quiz")


class GenerateQuizUseCase:
    """
    Use Case 3: Generates Bloom's taxonomy educational QuizSets grounded in retrieved context.
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
        payload: RetrieverPayload,
        version: Optional[str] = None,
        temperature: float = 0.2,
        bypass_cache: bool = False,
    ) -> QuizSet:
        logger.info(f"Executing GenerateQuizUseCase for Topic: '{payload.topic}'")

        template_vars = payload.to_template_vars()
        prompt = self.prompt_manager.prepare_prompt(
            template_name="quiz_generation",
            version=version,
            variables=template_vars,
        )

        cache_key = self.cache_service.generate_cache_key(
            prompt=prompt,
            schema=QuizSet,
            temperature=temperature,
        )

        if not bypass_cache:
            cached_quiz = await self.cache_service.get_cached_structured(cache_key, QuizSet)
            if cached_quiz:
                return cached_quiz

        quiz_set: QuizSet = await self.llm_provider.generate_structured(
            prompt=prompt,
            response_schema=QuizSet,
            temperature=temperature,
        )

        await self.cache_service.set_cached_structured(cache_key, quiz_set)
        return quiz_set
