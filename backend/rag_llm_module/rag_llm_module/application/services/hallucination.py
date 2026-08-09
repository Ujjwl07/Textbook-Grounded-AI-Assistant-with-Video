from rag_llm_module.domain.entities.evaluation import HallucinationScore
from rag_llm_module.domain.interfaces.evaluator import IEvaluator
from rag_llm_module.domain.exceptions import HallucinationThresholdExceededError
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("application.hallucination_service")


class HallucinationDetectorService:
    """
    Application service that executes RAG Triad verification and enforces faithfulness threshold constraints.
    """

    def __init__(self, evaluator: IEvaluator, threshold: float = 0.85):
        self.evaluator = evaluator
        self.threshold = threshold

    async def verify_and_enforce(self, context: str, generated_text: str, raise_on_violation: bool = False) -> HallucinationScore:
        """
        Verifies faithfulness of generated text.
        If score is below threshold and raise_on_violation is True, raises HallucinationThresholdExceededError.
        """
        score = await self.evaluator.evaluate_faithfulness(context, generated_text)
        logger.info(f"Hallucination check: Faithfulness Score = {score.faithfulness_score:.2f} (Threshold = {self.threshold:.2f})")

        if score.faithfulness_score < self.threshold:
            logger.warning(f"Faithfulness score {score.faithfulness_score:.2f} violated threshold {self.threshold:.2f}")
            if raise_on_violation:
                raise HallucinationThresholdExceededError(score.faithfulness_score, self.threshold)

        return score
