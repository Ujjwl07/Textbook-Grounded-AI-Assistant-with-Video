import os
from functools import lru_cache
from typing import Optional
from pydantic import BaseModel, Field


class LLMSettings(BaseModel):
    """Configuration for LLM Providers (OpenAI, Anthropic, Mock, etc.)."""
    provider: str = Field(default="openai", description="llm provider name: openai | anthropic | mock")
    api_key: Optional[str] = Field(default=None, description="API Key for the provider")
    default_model: str = Field(default="gpt-4o", description="Default model ID to use")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int = Field(default=4096, ge=1)
    max_retries: int = Field(default=3, ge=0)
    request_timeout: float = Field(default=30.0, ge=1.0)


class CacheSettings(BaseModel):
    """Configuration for Prompt and LLM Caching."""
    enabled: bool = Field(default=True)
    backend: str = Field(default="memory", description="memory | redis")
    redis_url: str = Field(default="redis://localhost:6379/0")
    ttl_seconds: int = Field(default=86400, description="Cache TTL in seconds (default 24 hours)")


class PromptSettings(BaseModel):
    """Configuration for Prompt Templates & Manager."""
    templates_dir: str = Field(default="templates")
    default_script_version: str = Field(default="v1.0.0")
    default_scene_version: str = Field(default="v1.0.0")
    default_quiz_version: str = Field(default="v1.0.0")
    strict_variable_check: bool = Field(default=True)


class AppConfig(BaseModel):
    """Main Application Configuration Aggregate."""
    environment: str = Field(default="development", description="development | staging | production")
    hallucination_threshold: float = Field(default=0.85, ge=0.0, le=1.0)
    llm: LLMSettings = Field(default_factory=LLMSettings)
    cache: CacheSettings = Field(default_factory=CacheSettings)
    prompt: PromptSettings = Field(default_factory=PromptSettings)

    @classmethod
    def load_from_env(cls) -> "AppConfig":
        """Instantiate settings from environment variables with sensible defaults."""
        llm = LLMSettings(
            provider=os.getenv("LLM_PROVIDER", "openai"),
            api_key=os.getenv("LLM_API_KEY", os.getenv("OPENAI_API_KEY")),
            default_model=os.getenv("LLM_DEFAULT_MODEL", "gpt-4o"),
            temperature=float(os.getenv("LLM_TEMPERATURE", "0.2")),
            max_tokens=int(os.getenv("LLM_MAX_TOKENS", "4096")),
        )
        cache = CacheSettings(
            enabled=os.getenv("CACHE_ENABLED", "true").lower() in ("true", "1", "yes"),
            backend=os.getenv("CACHE_BACKEND", "memory"),
            redis_url=os.getenv("CACHE_REDIS_URL", "redis://localhost:6379/0"),
            ttl_seconds=int(os.getenv("CACHE_TTL_SECONDS", "86400")),
        )
        prompt = PromptSettings(
            templates_dir=os.getenv("PROMPT_TEMPLATES_DIR", "templates"),
            default_script_version=os.getenv("PROMPT_DEFAULT_SCRIPT_VERSION", "v1.0.0"),
            default_scene_version=os.getenv("PROMPT_DEFAULT_SCENE_VERSION", "v1.0.0"),
            default_quiz_version=os.getenv("PROMPT_DEFAULT_QUIZ_VERSION", "v1.0.0"),
            strict_variable_check=os.getenv("PROMPT_STRICT_CHECK", "true").lower() in ("true", "1", "yes"),
        )
        return cls(
            environment=os.getenv("APP_ENV", "development"),
            hallucination_threshold=float(os.getenv("HALLUCINATION_THRESHOLD", "0.85")),
            llm=llm,
            cache=cache,
            prompt=prompt,
        )


@lru_cache(maxsize=1)
def get_settings() -> AppConfig:
    """Singleton getter for application settings."""
    return AppConfig.load_from_env()
