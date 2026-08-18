from typing import List
from rag_llm_module.domain.entities.retrieval import RetrieverPayload
from rag_llm_module.domain.entities.evaluation import PromptBenchmarkReport
from rag_llm_module.application.use_cases.generate_script import GenerateScriptUseCase
from rag_llm_module.domain.interfaces.evaluator import IEvaluator
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("application.use_cases.compare_prompts")


class ComparePromptsUseCase:
    """
    Use Case 5: Benchmarks and compares output quality of two prompt versions (e.g. v1.0.0 vs v1.1.0).
    """

    def __init__(self, script_use_case: GenerateScriptUseCase, evaluator: IEvaluator):
        self.script_use_case = script_use_case
        self.evaluator = evaluator

    async def execute(
        self,
        template_name: str,
        version_a: str,
        version_b: str,
        test_payloads: List[RetrieverPayload],
    ) -> PromptBenchmarkReport:
        logger.info(f"Comparing prompt versions '{version_a}' vs '{version_b}' for template '{template_name}' over {len(test_payloads)} samples")

        score_a_total = 0.0
        score_b_total = 0.0

        for payload in test_payloads:
            # Run Version A
            script_a = await self.script_use_case.execute(payload, version=version_a, bypass_cache=True)
            text_a = " ".join([d.dialogue for d in script_a.dialogue])
            faith_a = await self.evaluator.evaluate_faithfulness(payload.retrieved_context, text_a)
            score_a_total += faith_a.faithfulness_score

            # Run Version B
            script_b = await self.script_use_case.execute(payload, version=version_b, bypass_cache=True)
            text_b = " ".join([d.dialogue for d in script_b.dialogue])
            faith_b = await self.evaluator.evaluate_faithfulness(payload.retrieved_context, text_b)
            score_b_total += faith_b.faithfulness_score

        count = max(len(test_payloads), 1)
        avg_a = score_a_total / count
        avg_b = score_b_total / count

        winner = version_a if avg_a >= avg_b else version_b

        return PromptBenchmarkReport(
            template_name=template_name,
            version_a=version_a,
            version_b=version_b,
            sample_count=count,
            version_a_metrics={"Average Faithfulness": avg_a},
            version_b_metrics={"Average Faithfulness": avg_b},
            winner_version=winner,
            summary_comparison=f"Version '{winner}' outperformed with higher average faithfulness ({max(avg_a, avg_b):.2f}).",
        )
