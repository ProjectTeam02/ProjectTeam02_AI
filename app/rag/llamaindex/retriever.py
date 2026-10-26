from __future__ import annotations

import logging

from app.core.config import Settings, get_settings
from app.core.exceptions import RetrievalError
from app.rag.retrieval.types import RetrievedDocument

logger = logging.getLogger(__name__)


class LlamaIndexRetriever:
    def __init__(self, index_manager=None, settings: Settings | None = None):
        self.settings = settings or get_settings()
        self.index_manager = index_manager

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        concept_id: str | None = None,
        stage_id: str | None = None,
    ) -> list[RetrievedDocument]:
        try:
            manager = self.index_manager
            if manager is None:
                from app.rag.llamaindex.index_manager import IndexManager

                manager = IndexManager(self.settings)
                self.index_manager = manager
            index = manager.get_or_create(self.settings.vector_store_collection)
            from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

            filters = [
                MetadataFilter(
                    key="review_status", value=self.settings.approved_review_status
                )
            ]
            if concept_id:
                filters.append(MetadataFilter(key="concept_id", value=concept_id))
            if stage_id:
                filters.append(MetadataFilter(key="stage_id", value=stage_id))
            llama_retriever = index.as_retriever(
                similarity_top_k=top_k, filters=MetadataFilters(filters=filters)
            )
            nodes = await llama_retriever.aretrieve(query)
        except Exception as exc:
            logger.exception("LlamaIndex retrieval failed")
            raise RetrievalError("vector retrieval failed") from exc

        results: list[RetrievedDocument] = []
        for item in nodes:
            node = item.node
            metadata = node.metadata or {}
            results.append(
                RetrievedDocument(
                    content=node.get_content(),
                    source=str(metadata.get("source", "unknown")),
                    score=float(item.score) if item.score is not None else None,
                    document_id=str(
                        metadata.get(
                            "document_id", node.ref_doc_id or "unknown-document"
                        )
                    ),
                    chunk_id=str(metadata.get("chunk_id", node.node_id)),
                    title=metadata.get("title"),
                    version=metadata.get("document_version")
                    or metadata.get("version")
                    or None,
                    source_id=metadata.get("source_id") or None,
                    source_url=metadata.get("source_url") or None,
                    concept_id=metadata.get("concept_id") or None,
                    stage_id=metadata.get("stage_id") or None,
                    review_status=str(metadata.get("review_status", "")),
                    license=metadata.get("license") or None,
                    published_at=metadata.get("published_at") or None,
                    updated_at=metadata.get("updated_at") or None,
                    content_hash=metadata.get("content_hash") or None,
                )
            )
        return results
