from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = Field(default="Frontrow AI Interview POC", validation_alias="APP_NAME")
    api_v1_prefix: str = Field(default="/api/v1", validation_alias="API_V1_PREFIX")
    environment: str = Field(default="local", validation_alias="ENVIRONMENT")
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        validation_alias="CORS_ORIGINS",
    )
    persistence_backend: str = Field(default="memory", validation_alias="PERSISTENCE_BACKEND")
    active_state_backend: str = Field(default="memory", validation_alias="ACTIVE_STATE_BACKEND")

    gemini_api_key: str = Field(default="", validation_alias="GEMINI_API_KEY")
    gemini_audio_model: str = Field(default="gemini-2.5-flash", validation_alias="GEMINI_AUDIO_MODEL")
    gemini_tts_model: str = Field(
        default="gemini-3.1-flash-tts-preview",
        validation_alias="GEMINI_TTS_MODEL",
    )
    gemini_tts_voice: str = Field(default="Kore", validation_alias="GEMINI_TTS_VOICE")
    enable_gemini: bool = Field(default=False, validation_alias="ENABLE_GEMINI")
    enable_tts: bool = Field(default=False, validation_alias="ENABLE_TTS")

    redis_url: str = Field(default="redis://localhost:6379/0", validation_alias="REDIS_URL")
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/frontrow",
        validation_alias="DATABASE_URL",
    )

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
