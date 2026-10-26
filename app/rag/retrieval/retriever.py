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
        concept_codes: list[str] | None = None,
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
            if concept_codes and document.concept_code not in concept_codes:
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
                        concept_code=document.concept_code,
                        stage_id=document.stage_id,
                        review_status=document.review_status,
                        license=document.license,
                        published_at=document.published_at,
                        updated_at=document.updated_at,
                        content_hash=document.content_hash,
                        term=document.term,
                        term_kr=document.term_kr,
                        term_en=document.term_en,
                        publisher=document.publisher,
                        document_name=document.document_name,
                        edition=document.edition,
                        printed_page=document.printed_page,
                        related_terms=document.related_terms,
                        retrieval_method=document.retrieval_method,
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
    """Retrieval policy combining exact BOK term matches and vector search."""

    def __init__(
        self,
        backend=None,
        top_k: int | None = None,
        exact_matcher=None,
        related_term_top_k: int = 2,
    ):
        self.backend = backend or InMemoryRetriever()
        self.top_k = top_k or get_settings().retrieval_top_k
        self.exact_matcher = exact_matcher
        self.related_term_top_k = max(0, related_term_top_k)

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        concept_id: str | None = None,
        stage_id: str | None = None,
        concept_codes: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        limit = top_k or self.top_k
        if concept_codes is None:
            semantic = await self.backend.retrieve(
                query,
                limit,
                concept_id=concept_id,
                stage_id=stage_id,
            )
        else:
            try:
                semantic = await self.backend.retrieve(
                    query,
                    limit,
                    concept_id=concept_id,
                    stage_id=stage_id,
                    concept_codes=concept_codes,
                )
            except TypeError:
                semantic = await self.backend.retrieve(
                    query,
                    limit,
                    concept_id=concept_id,
                    stage_id=stage_id,
                )
        exact_retrieve = getattr(self.backend, "retrieve_exact", None)
        if self.exact_matcher is None or exact_retrieve is None:
            return semantic
        terms = self.exact_matcher.match(query)
        exact = (
            await self._retrieve_exact(
                exact_retrieve,
                terms,
                limit,
                concept_id,
                stage_id,
                concept_codes,
            )
            if terms
            else []
        )
        return self._merge(exact, semantic, limit)

    async def retrieve_related(
        self,
        documents: list[RetrievedDocument],
        concept_id: str | None = None,
        stage_id: str | None = None,
        concept_codes: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        if not documents or self.related_term_top_k == 0:
            return documents
        exact_retrieve = getattr(self.backend, "retrieve_exact", None)
        if exact_retrieve is None:
            return documents
        related_terms: list[str] = []
        existing_terms = {document.term for document in documents if document.term}
        for document in documents:
            for term in document.related_terms or []:
                if term not in existing_terms and term not in related_terms:
                    related_terms.append(term)
                if len(related_terms) >= self.related_term_top_k:
                    break
            if len(related_terms) >= self.related_term_top_k:
                break
        if not related_terms:
            return documents
        related = await self._retrieve_exact(
            exact_retrieve,
            related_terms,
            self.related_term_top_k,
            concept_id,
            stage_id,
            concept_codes,
        )
        return self._merge(documents, related, self.top_k + self.related_term_top_k)

    @staticmethod
    async def _retrieve_exact(
        exact_retrieve,
        terms: list[str],
        top_k: int,
        concept_id: str | None,
        stage_id: str | None,
        concept_codes: list[str] | None,
    ):
        if concept_codes is None:
            return await exact_retrieve(
                terms, top_k, concept_id=concept_id, stage_id=stage_id
            )
        try:
            return await exact_retrieve(
                terms,
                top_k,
                concept_id=concept_id,
                stage_id=stage_id,
                concept_codes=concept_codes,
            )
        except TypeError:
            return await exact_retrieve(
                terms, top_k, concept_id=concept_id, stage_id=stage_id
            )

    @staticmethod
    def _merge(
        primary: list[RetrievedDocument],
        secondary: list[RetrievedDocument],
        limit: int,
    ) -> list[RetrievedDocument]:
        merged: list[RetrievedDocument] = []
        seen: set[tuple[str, str]] = set()
        for document in [*primary, *secondary]:
            key = document.citation_key()
            if key in seen:
                continue
            seen.add(key)
            merged.append(document)
            if len(merged) >= limit:
                break
        return merged
