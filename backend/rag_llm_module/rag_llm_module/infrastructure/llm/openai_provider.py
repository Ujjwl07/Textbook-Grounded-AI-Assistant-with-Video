from typing import Type, TypeVar, Optional
from pydantic import BaseModel
from rag_llm_module.domain.entities.prompt import RenderedPrompt
from rag_llm_module.domain.interfaces.llm_provider import ILLMProvider
from rag_llm_module.domain.exceptions import LLMProviderError
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("infrastructure.llm.openai_provider")

T = TypeVar("T", bound=BaseModel)


class OpenAILLMProvider(ILLMProvider):
    """
    OpenAI implementation of ILLMProvider supporting structured JSON Pydantic parsing.
    """

    def __init__(self, api_key: Optional[str] = None, default_model: str = "gpt-4o"):
        self.api_key = api_key
        self.default_model = default_model
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI
                self._client = AsyncOpenAI(api_key=self.api_key)
            except ImportError:
                raise LLMProviderError("The 'openai' package is required to use OpenAILLMProvider.")
        return self._client

    async def generate_structured(
        self,
        prompt: RenderedPrompt,
        response_schema: Type[T],
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> T:
        client = self._get_client()
        temp = temperature if temperature is not None else 0.2

        messages = []
        if prompt.system_prompt:
            messages.append({"role": "system", "content": prompt.system_prompt})
        messages.append({"role": "user", "content": prompt.user_prompt})

        try:
            logger.info(f"Invoking OpenAI API with model '{self.default_model}' for schema '{response_schema.__name__}'")
            response = await client.beta.chat.completions.parse(
                model=self.default_model,
                messages=messages,
                temperature=temp,
                response_format=response_schema,
            )
            parsed_result = response.choices[0].message.parsed
            if parsed_result is None:
                raise LLMProviderError("OpenAI returned null parsed object.")
            return parsed_result
        except Exception as e:
            logger.error(f"OpenAI structured completion failed: {e}")
            raise LLMProviderError(f"OpenAI API invocation error: {str(e)}") from e

    async def generate_text(
        self,
        prompt: RenderedPrompt,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        client = self._get_client()
        temp = temperature if temperature is not None else 0.2

        messages = []
        if prompt.system_prompt:
            messages.append({"role": "system", "content": prompt.system_prompt})
        messages.append({"role": "user", "content": prompt.user_prompt})

        try:
            response = await client.chat.completions.create(
                model=self.default_model,
                messages=messages,
                temperature=temp,
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            logger.error(f"OpenAI text completion failed: {e}")
            raise LLMProviderError(f"OpenAI API text invocation error: {str(e)}") from e
