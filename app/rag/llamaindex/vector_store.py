from __future__ import annotations

from sqlalchemy.engine import make_url

from app.core.config import Settings, get_settings


class VectorStoreFactory:
    """Build the configured LlamaIndex PostgreSQL/pgvector store."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create(self, collection: str | None = None):
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
