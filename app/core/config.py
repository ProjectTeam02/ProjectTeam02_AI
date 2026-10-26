from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ProjectTeam02 AI"
    environment: str = "development"
    # docker-compose exposes PostgreSQL on host port 5433. Containers override
    # this URL with the service hostname ``db`` and container port 5432.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/leren"
    # Provider credentials are intentionally separate.  An OpenRouter key must
    # never silently fall back to OPENAI_API_KEY (or vice versa).
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    llm_provider: str = "openrouter"
    llm_model: str = "openai/gpt-4o-mini"
    embedding_provider: str = "openrouter"
    embedding_model: str = "openai/text-embedding-3-small"
    llm_base_url: str | None = None
    embedding_base_url: str | None = None
    llm_timeout_seconds: float = 30.0
    internal_request_timeout_seconds: float = 45.0
    llm_max_output_tokens: int = 700
    embedding_dimension: int = 1536
    retrieval_top_k: int = 5
    retrieval_min_score: float = Field(default=0.3, ge=-1.0, le=1.0)
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
    bok_terms_path: str = "data/bok_terms_2026_rag.jsonl"
    bok_source_path: str = "data/bok_terms_2026.json"
    bok_hybrid_search_enabled: bool = True
    related_term_top_k: int = Field(default=2, ge=0, le=10)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator("llm_provider", "embedding_provider")
    @classmethod
    def normalize_provider(cls, value: str) -> str:
        return value.strip().lower()

    @field_validator("openrouter_api_key", "openai_api_key", mode="before")
    @classmethod
    def normalize_optional_secret(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @field_validator("llm_model", "embedding_model")
    @classmethod
    def validate_model_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("model name must not be empty")
        return value

    @field_validator("embedding_dimension", "retrieval_top_k", "context_max_tokens")
    @classmethod
    def positive_integer(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
