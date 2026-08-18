import hashlib
import json
from typing import Any, Dict, Optional, Type, TypeVar
from pydantic import BaseModel
from rag_llm_module.domain.entities.prompt import RenderedPrompt
from rag_llm_module.domain.interfaces.cache_provider import ICacheProvider
from rag_llm_module.config.logging_config import get_logger

logger = get_logger("application.cache_service")

T = TypeVar("T", bound=BaseModel)


class CacheService:
    """
    Application service managing payload hashing, cache keys,
    and Pydantic object serialization for LLM responses.
    """

    def __init__(self, cache_provider: ICacheProvider, enabled: bool = True, ttl_seconds: int = 86400):
        self.cache_provider = cache_provider
        self.enabled = enabled
        self.ttl_seconds = ttl_seconds

    def generate_cache_key(
        self,
        prompt: RenderedPrompt,
        schema: Type[BaseModel],
        temperature: float = 0.2,
        model_name: str = "gpt-4o",
    ) -> str:
        """
        Generates deterministic SHA-256 hash key for a prompt request.
        Key tuple: (template_name, template_version, system_prompt, user_prompt, schema_name, temperature, model)
        """
        raw_signature = json.dumps(
            {
                "template_name": prompt.template_name,
                "version": prompt.template_version,
                "system_prompt": prompt.system_prompt,
                "user_prompt": prompt.user_prompt,
                "schema": schema.__name__,
                "temperature": temperature,
                "model": model_name,
            },
            sort_keys=True,
        )
        hash_digest = hashlib.sha256(raw_signature.encode("utf-8")).hexdigest()
        return f"llm_cache:{hash_digest}"

    async def get_cached_structured(self, cache_key: str, schema: Type[T]) -> Optional[T]:
        """Fetch and deserialize cached Pydantic model response."""
        if not self.enabled:
            return None

        cached_str = await self.cache_provider.get(cache_key)
        if not cached_str:
            return None

        try:
            logger.info(f"Cache HIT for key: {cache_key}")
            data = json.loads(cached_str)
            return schema.model_validate(data)
        except Exception as e:
            logger.warning(f"Failed to deserialize cache payload for {cache_key}: {e}")
            return None

    async def set_cached_structured(self, cache_key: str, response_obj: BaseModel) -> None:
        """Serialize and cache Pydantic model response."""
        if not self.enabled:
            return

        try:
            payload_str = response_obj.model_dump_json()
            await self.cache_provider.set(cache_key, payload_str, ttl_seconds=self.ttl_seconds)
            logger.debug(f"Successfully cached response for key: {cache_key}")
        except Exception as e:
            logger.error(f"Failed to cache response for {cache_key}: {e}")
