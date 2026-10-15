from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "ProjectTeam02 AI"
    environment: str = "development"
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/leren"
    openai_api_key: str | None = None
    vector_store_collection: str = "projectteam02"


@lru_cache
def get_settings() -> Settings:
    return Settings()
