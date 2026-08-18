"""
Domain-specific Exception classes for LLM & Prompt Engineering module.
"""

class RAGModuleException(Exception):
    """Base exception for all domain errors."""
    pass


class PromptTemplateNotFoundError(RAGModuleException):
    """Raised when a requested prompt template or template version is missing."""
    def __init__(self, template_name: str, version: str):
        self.template_name = template_name
        self.version = version
        super().__init__(f"Prompt template '{template_name}' with version '{version}' was not found.")


class PromptRenderError(RAGModuleException):
    """Raised when prompt variable validation or Jinja2 rendering fails."""
    pass


class LLMProviderError(RAGModuleException):
    """Raised when an LLM API call fails or yields invalid response format."""
    pass


class HallucinationThresholdExceededError(RAGModuleException):
    """Raised when generated output fails faithfulness threshold check."""
    def __init__(self, score: float, threshold: float):
        self.score = score
        self.threshold = threshold
        super().__init__(f"Hallucination verification failed: score {score:.2f} below threshold {threshold:.2f}.")


class InvalidSchemaError(RAGModuleException):
    """Raised when model output fails domain Pydantic validation."""
    pass
