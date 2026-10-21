from __future__ import annotations

from urllib.parse import urlparse

from app.core.config import Settings, get_settings


class VectorStoreFactory:
    """Build the configured LlamaIndex PostgreSQL/pgvector store."""

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create(self, collection: str | None = None):
        from llama_index.vector_stores.postgres import PGVectorStore

        parsed = urlparse(self.settings.database_url.replace("+asyncpg", ""))
        return PGVectorStore.from_params(
            host=parsed.hostname or "localhost",
            port=str(parsed.port or 5432),
            database=(parsed.path or "/leren").lstrip("/"),
            user=parsed.username or "postgres",
            password=parsed.password or "",
            table_name=collection or self.settings.vector_store_collection,
            embed_dim=self.settings.embedding_dimension,
        )
