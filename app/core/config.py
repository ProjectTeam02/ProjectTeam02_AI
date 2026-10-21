from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ProjectTeam02 AI"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/leren"
    openai_api_key: str | None = None
    llm_model: str = "gpt-4o-mini"
    embedding_model: str = "text-embedding-3-small"
    llm_base_url: str | None = None
    embedding_base_url: str | None = None
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 700
    embedding_dimension: int = 1536
    retrieval_top_k: int = 5
    context_max_tokens: int = 3000
    history_max_messages: int = 12
    chunk_size: int = 700
    chunk_overlap: int = 100
    internal_api_token: str | None = None
    vector_store_collection: str = "projectteam02"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
