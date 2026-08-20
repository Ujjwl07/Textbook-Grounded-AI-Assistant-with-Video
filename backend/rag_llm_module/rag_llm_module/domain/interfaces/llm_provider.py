from typing import Protocol, Type, TypeVar, Optional
from pydantic import BaseModel
from rag_llm_module.domain.entities.prompt import RenderedPrompt

T = TypeVar("T", bound=BaseModel)


class ILLMProvider(Protocol):
    """Protocol interface for LLM operations (Dependency Inversion)."""

    async def generate_structured(
        self,
        prompt: RenderedPrompt,
        response_schema: Type[T],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> T:
        """
        Generate structured response matching the specified Pydantic response_schema.
        Must throw LLMProviderError on non-retryable failures.
        """
        ...

    async def generate_text(
        self,
        prompt: RenderedPrompt,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """Generate unstructured string response from rendered prompt."""
        ...
