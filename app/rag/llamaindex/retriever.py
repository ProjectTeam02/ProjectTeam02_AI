from __future__ import annotations

import asyncio
import logging

from app.core.config import Settings, get_settings
from app.rag.retrieval.types import RetrievedDocument

logger = logging.getLogger(__name__)


class LlamaIndexRetriever:
    def __init__(self, index_manager=None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.index_manager = index_manager

    async def retrieve(self, query: str, top_k: int = 5) -> list[RetrievedDocument]:
        try:
            manager = self.index_manager
            if manager is None:
                from app.rag.llamaindex.index_manager import IndexManager

                manager = IndexManager(self.settings)
                self.index_manager = manager
            index = await asyncio.to_thread(manager.get_or_create, self.settings.vector_store_collection)
            llama_retriever = index.as_retriever(similarity_top_k=top_k)
            nodes = await asyncio.to_thread(llama_retriever.retrieve, query)
        except Exception:
            logger.exception("LlamaIndex retrieval failed")
            return []

        results: list[RetrievedDocument] = []
        for item in nodes:
            node = item.node
            metadata = node.metadata or {}
            results.append(
                RetrievedDocument(
                    content=node.get_content(),
                    source=str(metadata.get("source", "unknown")),
                    score=float(item.score) if item.score is not None else None,
                    document_id=str(metadata.get("document_id", node.ref_doc_id or "unknown-document")),
                    chunk_id=str(metadata.get("chunk_id", node.node_id)),
                    title=metadata.get("title"),
                    version=metadata.get("version") or None,
                )
            )
        return results
