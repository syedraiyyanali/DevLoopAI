from functools import lru_cache

from pydantic import field_validator
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
    log_level: str = "INFO"

    api_prefix: str = "/api/v1"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5-coder:7b"

    cors_origins: str = (
        "http://localhost:3000,"
        "http://127.0.0.1:3000"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="DEVLOOPAI_",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """
        Convert the comma-separated CORS origins into a clean list.
        """
        return [
            origin.strip()
            for origin in self.cors_origins.split(",")
            if origin.strip()
        ]

    @field_validator("log_level")
    @classmethod
    def normalize_log_level(cls, value: str) -> str:
        """
        Normalize logging levels so configuration stays predictable.
        """
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        normalized_value = value.strip().upper()

        if normalized_value not in valid_levels:
            raise ValueError(
                "log_level must be one of DEBUG, INFO, WARNING, ERROR, or CRITICAL"
            )

        return normalized_value


@lru_cache
def get_settings() -> Settings:
    """
    Create and cache the application settings.
    """
    return Settings()


settings = get_settings()
