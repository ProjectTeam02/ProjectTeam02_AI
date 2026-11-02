# 파일 역할: LlamaIndex 기반 RAG 검색·생성·메모리·인덱싱 기능을 제공합니다.
from __future__ import annotations

from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings


class VectorStoreFactory:
    """Build the configured LlamaIndex PostgreSQL/pgvector store."""

    def __init__(self, settings: Settings | None = None):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        self.settings = settings or get_settings()

    def create(self, collection: str | None = None):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        from llama_index.vector_stores.postgres import PGVectorStore

        async_url = make_url(self.settings.database_url)
        sync_url = async_url.set(drivername="postgresql+psycopg")
        return PGVectorStore(
            connection_string=sync_url,
            async_connection_string=async_url,
            table_name=collection or self.settings.vector_store_collection,
            schema_name=self.settings.vector_store_schema,
            embed_dim=self.settings.embedding_dimension,
            use_jsonb=True,
            perform_setup=True,
            initialization_fail_on_error=True,
        )
