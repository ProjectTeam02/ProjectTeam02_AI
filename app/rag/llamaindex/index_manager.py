from __future__ import annotations

from app.core.config import Settings, get_settings
from app.rag.llamaindex.embedding_model import EmbeddingModelFactory
from app.rag.llamaindex.vector_store import VectorStoreFactory


class IndexManager:
    """Create and cache LlamaIndex indexes for a pgvector collection."""

    def __init__(self, settings: Settings | None = None, vector_store_factory=None, embedding_factory=None):
        self.settings = settings or get_settings()
        self.vector_store_factory = vector_store_factory or VectorStoreFactory(self.settings)
        self.embedding_factory = embedding_factory or EmbeddingModelFactory(self.settings)
        self._indexes = {}

    def get_or_create(self, collection: str | None = None):
        collection = collection or self.settings.vector_store_collection
        if collection not in self._indexes:
            from llama_index.core import VectorStoreIndex

            vector_store = self.vector_store_factory.create(collection)
            self._indexes[collection] = VectorStoreIndex.from_vector_store(
                vector_store, embed_model=self.embedding_factory.create()
            )
        return self._indexes[collection]
