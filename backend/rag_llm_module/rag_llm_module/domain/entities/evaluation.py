from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional


class EvaluationMetric(BaseModel):
    """Specific prompt output evaluation score."""
    metric_name: str = Field(..., description="e.g. Faithfulness, Context Relevance, Schema Adherence")
    score: float = Field(..., ge=0.0, le=1.0, description="Normalized score between 0 and 1")
    rationale: str = Field(..., description="Justification/evidence for score")


class HallucinationScore(BaseModel):
    """Hallucination detection result."""
    is_faithful: bool
    faithfulness_score: float = Field(..., ge=0.0, le=1.0)
    unsupported_claims: List[str] = Field(default_factory=list)
    supported_claims: List[str] = Field(default_factory=list)


class PromptBenchmarkReport(BaseModel):
    """A/B Benchmark comparison report between prompt template versions."""
    template_name: str
    version_a: str
    version_b: str
    sample_count: int
    version_a_metrics: Dict[str, float]
    version_b_metrics: Dict[str, float]
    winner_version: str
    summary_comparison: str
