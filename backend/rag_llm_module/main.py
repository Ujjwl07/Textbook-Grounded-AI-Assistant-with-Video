import asyncio
import json
from typing import Optional
from rag_llm_module.config.settings import AppConfig, get_settings
from rag_llm_module.config.logging_config import setup_logging, get_logger
from rag_llm_module.domain.entities.retrieval import RetrieverPayload
from rag_llm_module.domain.interfaces.llm_provider import ILLMProvider
from rag_llm_module.domain.interfaces.prompt_repository import IPromptRepository
from rag_llm_module.domain.interfaces.cache_provider import ICacheProvider
from rag_llm_module.domain.interfaces.evaluator import IEvaluator
from rag_llm_module.infrastructure.prompt_loader.filesystem_loader import FileSystemPromptRepository
from rag_llm_module.infrastructure.cache.memory_cache import MemoryCacheProvider
from rag_llm_module.infrastructure.cache.redis_cache import RedisCacheProvider
from rag_llm_module.infrastructure.llm.mock_provider import MockLLMProvider
from rag_llm_module.infrastructure.llm.openai_provider import OpenAILLMProvider
from rag_llm_module.infrastructure.evaluation.faithfulness import FaithfulnessEvaluator
from rag_llm_module.application.services.prompt_manager import PromptManagerService
from rag_llm_module.application.services.cache_service import CacheService
from rag_llm_module.application.services.hallucination import HallucinationDetectorService
from rag_llm_module.application.use_cases.generate_script import GenerateScriptUseCase
from rag_llm_module.application.use_cases.convert_to_scene import ConvertToSceneUseCase
from rag_llm_module.application.use_cases.generate_quiz import GenerateQuizUseCase
from rag_llm_module.application.use_cases.evaluate_prompt import EvaluatePromptUseCase

logger = get_logger("main")


class Container:
    """Dependency Injection Container for assembly and wiring."""

    def __init__(self, config: Optional[AppConfig] = None):
        self.config = config or get_settings()

        # 1. Infrastructure Wiring
        self.prompt_repo: IPromptRepository = FileSystemPromptRepository(
            templates_dir=self.config.prompt.templates_dir
        )

        if self.config.cache.backend == "redis":
            self.cache_provider: ICacheProvider = RedisCacheProvider(redis_url=self.config.cache.redis_url)
        else:
            self.cache_provider = MemoryCacheProvider()

        if self.config.llm.provider == "openai" and self.config.llm.api_key:
            self.llm_provider: ILLMProvider = OpenAILLMProvider(
                api_key=self.config.llm.api_key,
                default_model=self.config.llm.default_model,
            )
        else:
            logger.info("Using MockLLMProvider for execution.")
            self.llm_provider = MockLLMProvider()

        self.evaluator: IEvaluator = FaithfulnessEvaluator(llm_provider=self.llm_provider)

        # 2. Application Services Wiring
        self.prompt_manager = PromptManagerService(
            repository=self.prompt_repo,
            strict_check=self.config.prompt.strict_variable_check,
        )
        self.cache_service = CacheService(
            cache_provider=self.cache_provider,
            enabled=self.config.cache.enabled,
            ttl_seconds=self.config.cache.ttl_seconds,
        )
        self.hallucination_detector = HallucinationDetectorService(
            evaluator=self.evaluator,
            threshold=self.config.hallucination_threshold,
        )

        # 3. Application Use Cases Wiring
        self.generate_script_uc = GenerateScriptUseCase(
            prompt_manager=self.prompt_manager,
            llm_provider=self.llm_provider,
            cache_service=self.cache_service,
            hallucination_detector=self.hallucination_detector,
        )
        self.convert_to_scene_uc = ConvertToSceneUseCase(
            prompt_manager=self.prompt_manager,
            llm_provider=self.llm_provider,
            cache_service=self.cache_service,
        )
        self.generate_quiz_uc = GenerateQuizUseCase(
            prompt_manager=self.prompt_manager,
            llm_provider=self.llm_provider,
            cache_service=self.cache_service,
        )
        self.evaluate_prompt_uc = EvaluatePromptUseCase(evaluator=self.evaluator)


async def main():
    setup_logging(level="INFO")
    logger.info("Initializing LLM & Prompt Engineering RAG Downstream Pipeline...")

    container = Container()

    # Incoming Retriever payload contract sample from Team 1
    raw_retriever_input = {
        "subject": "Physics",
        "topic": "Newton's Laws of Motion",
        "chapter_name": "Laws of Motion",
        "chapter_num": 3,
        "class_num": 11,
        "retrieved_context": (
            "Newton's First Law states that every object will remain at rest or in uniform motion in a straight line "
            "unless compelled to change its state by the action of an external force. This tendency to resist changes "
            "in a state of motion is called inertia. Mass is the quantitative measure of inertia."
        ),
        "metadata": {"chunk_id": "c92-phys-ch3-004", "score": 0.94},
    }

    # Step 1: Validate payload entity
    retriever_payload = RetrieverPayload.model_validate(raw_retriever_input)
    logger.info(f"Validated payload from Retriever: {retriever_payload.subject} - Class {retriever_payload.class_num}")

    # Step 2: Generate Educational Script
    script = await container.generate_script_uc.execute(retriever_payload)
    print("\n" + "=" * 60)
    print("1. EDUCATIONAL SCRIPT OUTPUT:")
    print("=" * 60)
    print(json.dumps(script.model_dump(), indent=2))

    # Step 3: Convert Script into Scene JSON Graph
    scene_graph = await container.convert_to_scene_uc.execute(script)
    print("\n" + "=" * 60)
    print("2. SCENE GRAPH JSON OUTPUT:")
    print("=" * 60)
    print(json.dumps(scene_graph.model_dump(), indent=2))

    # Step 4: Generate Assessment Quiz Set
    quiz_set = await container.generate_quiz_uc.execute(retriever_payload)
    print("\n" + "=" * 60)
    print("3. QUIZ SET JSON OUTPUT:")
    print("=" * 60)
    print(json.dumps(quiz_set.model_dump(), indent=2))

    # Step 5: Evaluate Prompt Quality & Faithfulness
    script_text = " ".join([d.dialogue for d in script.dialogue])
    metrics = await container.evaluate_prompt_uc.execute(retriever_payload.retrieved_context, script_text)
    print("\n" + "=" * 60)
    print("4. EVALUATION METRICS REPORT:")
    print("=" * 60)
    for m in metrics:
        print(f"- {m.metric_name}: {m.score:.2f} ({m.rationale})")


if __name__ == "__main__":
    asyncio.run(main())
