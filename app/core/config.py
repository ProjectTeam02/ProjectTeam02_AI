# 파일 역할: 환경 설정, 예외, 로깅 등 애플리케이션 공통 기능을 제공합니다.
import re
from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    app_name: str = "ProjectTeam02 AI"
    environment: str = "development"
    # docker-compose exposes PostgreSQL on host port 5433. Containers override
    # this URL with the service hostname ``db`` and container port 5432.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5433/leren"
    # Provider credentials are intentionally separate. An OpenRouter key must
    # never silently fall back to OPENAI_API_KEY (or vice versa).
    openrouter_api_key: str | None = None
    openai_api_key: str | None = None
    llm_provider: str = "openrouter"
    llm_model: str = "openai/gpt-5.6-sol"
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
    concept_graph_max_depth: int = Field(default=2, ge=0, le=5)
    concept_graph_max_nodes: int = Field(default=20, ge=1, le=100)
    concept_graph_max_tokens: int = Field(default=600, ge=100, le=3000)
    history_max_messages: int = 12
    history_max_tokens: int = 1200
    chunk_size: int = 700
    chunk_overlap: int = 100
    internal_api_token: str | None = None
    question_evidence_path: str | None = None
    question_approval_label_path: str | None = None
    question_existing_path: str | None = None
    question_max_count: int = Field(default=20, ge=1, le=100)
    question_max_revision_attempts: int = Field(default=2, ge=0, le=10)
    vector_store_collection: str = "projectteam02"
    vector_store_schema: str = "public"
    # 운영(RDS)은 false: 벡터 테이블은 백엔드 레포 04_ai_vector_table.sql이 만든다.
    # 로컬 일회용 DB에서만 true로 두면 LlamaIndex가 스키마·확장·테이블을 만든다.
    vector_store_perform_setup: bool = False
    approved_review_status: str = "approved"
    grounding_min_overlap: float = Field(default=0.12, ge=0.0, le=1.0)
    bok_terms_path: str = "data/bok_terms_2026_rag.jsonl"
    bok_source_path: str = "data/bok_terms_2026.json"
    bok_hybrid_search_enabled: bool = True
    related_term_top_k: int = Field(default=2, ge=0, le=10)
    sparse_retrieval_enabled: bool = True
    reranking_enabled: bool = False
    retrieval_fusion_k: int = Field(default=60, ge=1, le=1000)
    rag_stage_timeout_seconds: float = Field(default=20.0, gt=0.0)
    rag_max_retries: int = Field(default=1, ge=0, le=3)
    llm_input_cost_per_1k: float | None = Field(default=None, ge=0.0)
    llm_output_cost_per_1k: float | None = Field(default=None, ge=0.0)

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

    @field_validator("vector_store_schema")
    @classmethod
    def validate_schema_name(cls, value: str) -> str:
        value = value.strip()
        if not value or not re.fullmatch(r"[a-z_][a-z0-9_]*", value):
            raise ValueError(
                "VECTOR_STORE_SCHEMA must be a lowercase PostgreSQL identifier"
            )
        return value

    @model_validator(mode="after")
    def validate_production_safety(self) -> "Settings":
        if self.environment.strip().casefold() != "production":
            return self
        if not self.internal_api_token:
            raise ValueError("INTERNAL_API_TOKEN is required in production")
        if self.vector_store_schema == "public":
            raise ValueError(
                "VECTOR_STORE_SCHEMA must not be public in production; use the "
                "backend-owned AI schema"
            )
        if self.vector_store_perform_setup:
            raise ValueError(
                "VECTOR_STORE_PERFORM_SETUP must be false in production"
            )
        return self

    @field_validator("embedding_dimension", "retrieval_top_k", "context_max_tokens")
    @classmethod
    def positive_integer(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("must be greater than zero")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
