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
            from llama_index.core.vector_stores import MetadataFilters

            filters = self._filters(concept_id, stage_id)
            llama_retriever = index.as_retriever(
                similarity_top_k=top_k, filters=MetadataFilters(filters=filters)
            )
            nodes = await llama_retriever.aretrieve(query)
            if concept_id or stage_id:
                from llama_index.core.vector_stores import MetadataFilter

                global_filters = self._filters(None, None)
                global_filters.append(
                    MetadataFilter(key="knowledge_scope", value="global")
                )
                global_retriever = index.as_retriever(
                    similarity_top_k=top_k,
                    filters=MetadataFilters(filters=global_filters),
                )
                global_nodes = await global_retriever.aretrieve(query)
                seen = {item.node.node_id for item in nodes}
                nodes.extend(
                    item for item in global_nodes if item.node.node_id not in seen
                )
                nodes = sorted(
                    nodes,
                    key=lambda item: item.score if item.score is not None else -1.0,
                    reverse=True,
                )[:top_k]
        except Exception as exc:
            logger.exception("LlamaIndex retrieval failed")
            raise RetrievalError("vector retrieval failed") from exc

        return [
            self._document(item, "vector")
            for item in nodes
            if item.score is not None
            and float(item.score) >= self.settings.retrieval_min_score
        ]

    async def retrieve_exact(
        self,
        terms: list[str],
        top_k: int = 5,
        concept_id: str | None = None,
        stage_id: str | None = None,
    ) -> list[RetrievedDocument]:
        if not terms:
            return []
        try:
            manager = self.index_manager
            if manager is None:
                from app.rag.llamaindex.index_manager import IndexManager

                manager = IndexManager(self.settings)
                self.index_manager = manager
            index = manager.get_or_create(self.settings.vector_store_collection)
            from llama_index.core.vector_stores import MetadataFilter, MetadataFilters

            results: list[RetrievedDocument] = []
            per_term_limit = max(1, min(2, top_k))
            for term in terms:
                filters = self._filters(None, None)
                filters.append(MetadataFilter(key="term", value=term))
                filters.append(
                    MetadataFilter(key="knowledge_scope", value="global")
                )
                retriever = index.as_retriever(
                    similarity_top_k=per_term_limit,
                    filters=MetadataFilters(filters=filters),
                )
                nodes = await retriever.aretrieve(term)
                results.extend(self._document(item, "exact") for item in nodes)
                if len(results) >= top_k:
                    break
            return results[:top_k]
        except Exception as exc:
            logger.exception("LlamaIndex exact term retrieval failed")
            raise RetrievalError("exact term retrieval failed") from exc

    def _filters(self, concept_id: str | None, stage_id: str | None):
        from llama_index.core.vector_stores import MetadataFilter

        filters = [
            MetadataFilter(
                key="review_status", value=self.settings.approved_review_status
            )
        ]
        if concept_id:
            filters.append(MetadataFilter(key="concept_id", value=concept_id))
        if stage_id:
            filters.append(MetadataFilter(key="stage_id", value=stage_id))
        return filters

    @staticmethod
    def _document(item, retrieval_method: str) -> RetrievedDocument:
        node = item.node
        metadata = node.metadata or {}
        printed_page = metadata.get("printed_page")
        return RetrievedDocument(
            content=node.get_content(),
            source=str(metadata.get("source", "unknown")),
            score=(
                1.0
                if retrieval_method == "exact"
                else float(item.score) if item.score is not None else None
            ),
            document_id=str(
                metadata.get("document_id", node.ref_doc_id or "unknown-document")
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
            term=metadata.get("term") or None,
            term_kr=metadata.get("term_kr") or None,
            term_en=metadata.get("term_en") or None,
            publisher=metadata.get("publisher") or None,
            document_name=metadata.get("document") or None,
            edition=metadata.get("edition") or None,
            printed_page=int(printed_page) if printed_page else None,
            related_terms=list(metadata.get("related_terms") or []),
            retrieval_method=retrieval_method,
        )
