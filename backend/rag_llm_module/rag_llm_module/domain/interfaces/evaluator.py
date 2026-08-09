from typing import Protocol, List
from rag_llm_module.domain.entities.evaluation import EvaluationMetric, HallucinationScore


class IEvaluator(Protocol):
    """Protocol interface for output quality & hallucination evaluation."""

    async def evaluate_faithfulness(self, context: str, generated_text: str) -> HallucinationScore:
        """Evaluate factual faithfulness of generated text against retrieved context."""
        ...

    async def evaluate_quality_metrics(self, context: str, generated_text: str) -> List[EvaluationMetric]:
        """Calculate broad quality metrics (Relevance, Clarity, Schema match)."""
        ...
