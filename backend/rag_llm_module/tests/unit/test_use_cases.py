import pytest
from rag_llm_module.domain.entities.retrieval import RetrieverPayload
from rag_llm_module.domain.entities.script import EducationalScript
from rag_llm_module.domain.entities.scene import SceneGraph
from rag_llm_module.domain.entities.quiz import QuizSet
from rag_llm_module.infrastructure.prompt_loader.filesystem_loader import FileSystemPromptRepository
from rag_llm_module.infrastructure.cache.memory_cache import MemoryCacheProvider
from rag_llm_module.infrastructure.llm.mock_provider import MockLLMProvider
from rag_llm_module.infrastructure.evaluation.faithfulness import FaithfulnessEvaluator
from rag_llm_module.application.services.prompt_manager import PromptManagerService
from rag_llm_module.application.services.cache_service import CacheService
from rag_llm_module.application.services.hallucination import HallucinationDetectorService
from rag_llm_module.application.use_cases.generate_script import GenerateScriptUseCase
from rag_llm_module.application.use_cases.convert_to_scene import ConvertToSceneUseCase
from rag_llm_module.application.use_cases.generate_quiz import GenerateQuizUseCase


@pytest.fixture
def retriever_payload():
    return RetrieverPayload(
        subject="Physics",
        topic="Newton's Laws",
        chapter_name="Laws of Motion",
        chapter_num=3,
        class_num=11,
        retrieved_context="An object at rest remains at rest unless acted upon by a net force.",
        metadata={"source": "test"},
    )


@pytest.fixture
def container_setup():
    repo = FileSystemPromptRepository(templates_dir="templates")
    prompt_manager = PromptManagerService(repository=repo)
    cache_provider = MemoryCacheProvider()
    cache_service = CacheService(cache_provider=cache_provider, enabled=True)
    llm_provider = MockLLMProvider()
    evaluator = FaithfulnessEvaluator(llm_provider=llm_provider)
    hallucination_detector = HallucinationDetectorService(evaluator=evaluator, threshold=0.85)

    return {
        "prompt_manager": prompt_manager,
        "llm_provider": llm_provider,
        "cache_service": cache_service,
        "hallucination_detector": hallucination_detector,
        "evaluator": evaluator,
    }


@pytest.mark.asyncio
async def test_generate_script_use_case_success(container_setup, retriever_payload):
    use_case = GenerateScriptUseCase(
        prompt_manager=container_setup["prompt_manager"],
        llm_provider=container_setup["llm_provider"],
        cache_service=container_setup["cache_service"],
        hallucination_detector=container_setup["hallucination_detector"],
    )

    script = await use_case.execute(retriever_payload)
    assert isinstance(script, EducationalScript)
    assert script.target_grade == 11
    assert len(script.dialogue) > 0


@pytest.mark.asyncio
async def test_convert_to_scene_use_case_success(container_setup, retriever_payload):
    script_uc = GenerateScriptUseCase(
        prompt_manager=container_setup["prompt_manager"],
        llm_provider=container_setup["llm_provider"],
        cache_service=container_setup["cache_service"],
        hallucination_detector=container_setup["hallucination_detector"],
    )
    script = await script_uc.execute(retriever_payload)

    scene_uc = ConvertToSceneUseCase(
        prompt_manager=container_setup["prompt_manager"],
        llm_provider=container_setup["llm_provider"],
        cache_service=container_setup["cache_service"],
    )

    scene_graph = await scene_uc.execute(script)
    assert isinstance(scene_graph, SceneGraph)
    assert len(scene_graph.scenes) > 0


@pytest.mark.asyncio
async def test_generate_quiz_use_case_success(container_setup, retriever_payload):
    quiz_uc = GenerateQuizUseCase(
        prompt_manager=container_setup["prompt_manager"],
        llm_provider=container_setup["llm_provider"],
        cache_service=container_setup["cache_service"],
    )

    quiz_set = await quiz_uc.execute(retriever_payload)
    assert isinstance(quiz_set, QuizSet)
    assert len(quiz_set.questions) > 0
    assert quiz_set.questions[0].correct_option_id in ["A", "B", "C", "D"]
