from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ProjectTeam02 AI"
    environment: str = "development"
    # docker-compose exposes PostgreSQL on host port 5433. Containers override
    # this URL with the service hostname ``db`` and container port 5432.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/leren"
    openai_api_key: str | None = None
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    llm_base_url: str | None = None
    embedding_base_url: str | None = None
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 700
    embedding_dimension: int = 1536
    retrieval_top_k: int = 5
    context_max_tokens: int = 3000
    history_max_messages: int = 12
    history_max_tokens: int = 1200
    chunk_size: int = 700
    chunk_overlap: int = 100
    internal_api_token: str | None = None
    vector_store_collection: str = "projectteam02"
    vector_store_schema: str = "public"
    approved_review_status: str = "approved"
    grounding_min_overlap: float = Field(default=0.12, ge=0.0, le=1.0)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("llm_provider", "embedding_provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("embedding_dimension", "retrieval_top_k", "context_max_tokens")
    @classmethod
    def positive_integer(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
