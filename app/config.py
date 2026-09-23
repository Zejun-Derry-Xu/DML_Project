from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "ReturnFlow"
    environment: str = "development"
    database_url: str = "postgresql+psycopg://returnflow:returnflow@localhost:5432/returnflow"
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:5173"])
    question_ttl_minutes: int = 10
    llm_provider: str = "rules"
    llm_model: str = "qwen3:4b"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_api_key: str = ""
    llm_timeout_seconds: float = 15.0
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
