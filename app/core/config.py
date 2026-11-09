from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ProjectTeam02 AI"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/leren"
    openai_api_key: str | None = None
    openrouter_api_key: str | None = None
    llm_provider: str = "openrouter"
    llm_model: str = "openai/gpt-4o-mini"
    llm_base_url: str = "https://openrouter.ai/api/v1"
    llm_timeout_seconds: float = 30.0
    internal_api_token: str | None = None
    question_evidence_path: str | None = None
    question_approval_label_path: str | None = None
    question_existing_path: str | None = None
    question_max_count: int = 20
    question_max_revision_attempts: int = 2
    vector_store_collection: str = "projectteam02"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
