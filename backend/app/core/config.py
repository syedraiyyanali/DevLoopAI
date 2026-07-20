from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Central configuration for the DevLoopAI backend.

    Values can be overridden through environment variables
    or the backend/.env file.
    """

    app_name: str = "DevLoopAI API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = True

    api_prefix: str = "/api/v1"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """
    Create and cache the application settings.

    Caching prevents the .env file from being read repeatedly.
    """
    return Settings()


settings = get_settings()