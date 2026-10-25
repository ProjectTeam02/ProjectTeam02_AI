from __future__ import annotations

import re

from app.core.config import get_settings
from app.rag.retrieval.types import RetrievedDocument


class InMemoryRetriever:
    """Deterministic lexical retriever used for fixtures and no-key development runs."""

    def __init__(self, documents: list[RetrievedDocument] | None = None):
        self.documents = documents or []

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        concept_id: str | None = None,
        stage_id: str | None = None,
    ) -> list[RetrievedDocument]:
        query_tokens = self._tokens(query)
        scored: list[RetrievedDocument] = []
        for document in self.documents:
            if document.review_status != "approved":
                continue
            if concept_id and document.concept_id != concept_id:
                continue
            if stage_id and document.stage_id != stage_id:
                continue
            content_tokens = self._tokens(
                document.content + " " + (document.title or "")
            )
            overlap = len(query_tokens & content_tokens)
            if overlap:
                scored.append(
                    RetrievedDocument(
                        content=document.content,
                        source=document.source,
                        score=overlap / max(len(query_tokens), 1),
                        document_id=document.document_id,
                        chunk_id=document.chunk_id,
                        title=document.title,
                        version=document.version,
                        source_id=document.source_id,
                        source_url=document.source_url,
                        concept_id=document.concept_id,
                        stage_id=document.stage_id,
                        review_status=document.review_status,
                        license=document.license,
                        published_at=document.published_at,
                        updated_at=document.updated_at,
                        content_hash=document.content_hash,
                    )
                )
        scored.sort(key=lambda item: item.score or 0, reverse=True)
        return scored[:top_k]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        # Keep Latin abbreviations such as GDP separate from Korean particles
        # ("GDP가"), otherwise a follow-up query misses the same concept.
        return set(re.findall(r"[A-Za-z0-9]{2,}|[가-힣]{2,}", text.lower()))


class Retriever:
    def __init__(self, backend=None, top_k: int | None = None):
        self.backend = backend or InMemoryRetriever()
        self.top_k = top_k or get_settings().retrieval_top_k

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        concept_id: str | None = None,
        stage_id: str | None = None,
    ) -> list[RetrievedDocument]:
        return await self.backend.retrieve(
            query,
            top_k or self.top_k,
            concept_id=concept_id,
            stage_id=stage_id,
        )
