from functools import lru_cache
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BACKEND_DIR = Path(__file__).resolve().parents[2]
load_dotenv(BACKEND_DIR / ".env")


class Settings(BaseSettings):
    app_name: str = "Generic Textbook Assistant API"
    app_version: str = "0.1.0"
    environment: str = "development"
    api_prefix: str = "/api"
    cors_origins: List[str] = Field(default_factory=lambda: ["http://localhost:5173", "http://localhost:3000"])

    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db_name: str = "textbook_assistant"

    jwt_secret_key: str = ""
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24

    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_folder: str = "textbook-assistant/videos"

    video_output_dir: Path = BACKEND_DIR / "outputs" / "videos"
    audio_output_dir: Path = BACKEND_DIR / "outputs" / "audio"
    slide_output_dir: Path = BACKEND_DIR / "outputs" / "slides"
    logs_dir: Path = BACKEND_DIR / "outputs" / "logs"
    chunks_log_path: Path = BACKEND_DIR / "outputs" / "logs" / "retrieved_chunks.log"
    generation_mock_delay_seconds: float = 0.15

    # --- Video assembly (Purnika) ---
    video_fps: int = 24
    video_width: int = 1280
    video_height: int = 720
    # x264 speed/compression trade-off. Slide-based content compresses well even
    # at fast presets, and encoding dominates total generation time.
    video_preset: str = "veryfast"
    # 0 = use every available core.
    video_threads: int = 0
    vmake_api_key: str = ""
    vmake_enabled: bool = False

    # --- TTS / audio post-processing (Pallika) ---
    audio_target_lufs: float = -16.0
    audio_silence_threshold_db: float = -45.0
    audio_postprocess_enabled: bool = True

    qdrant_url: str = ""
    qdrant_api_key: str = ""
    qdrant_collection: str = "textbook_chunks"
    embedding_model: str = "all-MiniLM-L6-v2"

    # Below this similarity a topic is treated as absent from the corpus rather
    # than matched to the least-bad chapter. Measured over 11 topics, the
    # in-corpus and off-corpus scores do not overlap: the weakest real topic
    # ("circulation of blood") scores 0.482 and the strongest miss ("Quantum
    # Tunnelling") 0.312, with "Blockchain" at 0.147. 0.40 sits in that gap.
    # Configurable because the gap is a property of the corpus, not a constant.
    topic_match_threshold: float = 0.40

    # --- LLM Integration (Google Gemini) ---
    gemini_api_key: str = ""
    llm_provider: str = "gemini"
    llm_model: str = "gemini-3.6-flash"
    # gemini-3.6-flash reasons before answering and those thinking tokens come
    # out of this budget: a five-scene script measured 1,097 thinking tokens
    # against 803 of actual output. At the old 2,048 the response came back
    # finishReason=MAX_TOKENS, truncated mid-JSON. thinkingConfig is not
    # accepted by this model (HTTP 400), so headroom is the available lever.
    llm_max_output_tokens: int = 8192

    model_config = SettingsConfigDict(
        env_file=str(BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    cache_ttl_seconds: int = 2592000

    @property
    def cloudinary_enabled(self) -> bool:
        return bool(self.cloudinary_cloud_name and self.cloudinary_api_key and self.cloudinary_api_secret)

    @property
    def vmake_active(self) -> bool:
        """VMake backgrounds run only when a key is present AND the flag is on."""
        return bool(self.vmake_enabled and self.vmake_api_key)

    @property
    def video_size(self) -> tuple:
        return (self.video_width, self.video_height)

    @model_validator(mode="after")
    def validate_security_settings(self):
        if len(self.jwt_secret_key) < 8:
            raise ValueError("JWT_SECRET_KEY must be set to a value of at least 8 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
