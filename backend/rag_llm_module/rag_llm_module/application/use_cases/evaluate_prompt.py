from typing import List
from rag_llm_module.domain.entities.evaluation import EvaluationMetric
from rag_llm_module.domain.interfaces.evaluator import IEvaluator
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("application.use_cases.evaluate_prompt")


class EvaluatePromptUseCase:
    """
    Use Case 4: Evaluates prompt output quality & factual faithfulness metrics.
    """

    def __init__(self, evaluator: IEvaluator):
        self.evaluator = evaluator

    async def execute(self, context: str, generated_text: str) -> List[EvaluationMetric]:
        logger.info("Executing EvaluatePromptUseCase quality evaluation")
        return await self.evaluator.evaluate_quality_metrics(context, generated_text)
