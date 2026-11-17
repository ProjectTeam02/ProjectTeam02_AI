# 파일 역할: LlamaIndex 기반 RAG 검색·생성·메모리·인덱싱 기능을 제공합니다.
from __future__ import annotations

import logging
import re
from dataclasses import replace

from app.core.config import get_settings
from app.core.exceptions import RetrievalError
from app.rag.retrieval.types import RetrievedDocument

logger = logging.getLogger(__name__)


class InMemoryRetriever:
    """Deterministic lexical retriever used for fixtures and no-key development runs."""

    def __init__(
        self,
        documents: list[RetrievedDocument] | None = None,
        approved_status: str | None = None,
    ):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        self.documents = documents or []
        self.approved_status = approved_status or get_settings().approved_review_status

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        concept_id: str | None = None,
        stage_id: str | None = None,
        concept_codes: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        query_tokens = self._tokens(query)
        scored: list[RetrievedDocument] = []
        for document in self.documents:
            if document.review_status != self.approved_status:
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
            overlap = sum(
                1
                for token in query_tokens
                if any(_surface_match(token, candidate) for candidate in content_tokens)
            )
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
                        knowledge_scope=document.knowledge_scope,
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
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        return set(re.findall(r"[A-Za-z0-9]{2,}|[가-힣]{2,}", text.lower()))


class Retriever:
    """Retrieval policy combining dense, sparse, exact, and optional reranking.

    The dense backend remains the primary backend for compatibility. A sparse
    backend is optional so local fixtures and existing callers keep the old
    behavior, while production can use PostgreSQL full-text search without a
    new search service.
    """

    def __init__(
        self,
        backend=None,
        top_k: int | None = None,
        exact_matcher=None,
        related_term_top_k: int = 2,
        *,
        sparse_backend=None,
        reranker=None,
        fusion_k: int = 60,
        approved_status: str | None = None,
    ):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        self.backend = backend or InMemoryRetriever()
        self.top_k = top_k or get_settings().retrieval_top_k
        self.exact_matcher = exact_matcher
        self.related_term_top_k = max(0, related_term_top_k)
        self.sparse_backend = sparse_backend
        self.reranker = reranker
        self.fusion_k = max(1, fusion_k)
        self.approved_status = approved_status or getattr(
            getattr(self.backend, "settings", None),
            "approved_review_status",
            get_settings().approved_review_status,
        )
        self.last_strategy = "VECTOR"
        self.last_trace: dict[str, object] = {}
        self.last_limit = self.top_k

    async def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        concept_id: str | None = None,
        stage_id: str | None = None,
        concept_codes: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        limit = top_k if top_k is not None else self.top_k
        if limit <= 0:
            self.last_strategy = "NONE"
            self.last_trace = {"query": query, "limit": limit}
            return []
        self.last_limit = limit
        self.last_trace = {"query": query, "limit": limit}
        try:
            semantic, semantic_global_error = await self._retrieve_with_scope(
                self.backend,
                query,
                limit,
                concept_id,
                stage_id,
                concept_codes,
            )
        except RetrievalError:
            raise
        except Exception as exc:
            raise RetrievalError("retrieval failed") from exc
        sparse: list[RetrievedDocument] = []
        sparse_error: str | None = None
        sparse_global_error: str | None = None
        if self.sparse_backend is not None:
            try:
                sparse, sparse_global_error = await self._retrieve_with_scope(
                    self.sparse_backend,
                    query,
                    limit,
                    concept_id,
                    stage_id,
                    concept_codes,
                )
            except Exception as exc:
                # Sparse retrieval is an optimization over the existing dense
                # path. A temporary FTS/index issue must not cause an outage.
                sparse_error = type(exc).__name__
                logger.warning("sparse retrieval unavailable; using dense results")

        exact_retrieve = getattr(self.backend, "retrieve_exact", None)
        exact: list[RetrievedDocument] = []
        if self.exact_matcher is not None and exact_retrieve is not None:
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
            if concept_id or stage_id or concept_codes:
                try:
                    exact = self._merge(
                        exact,
                        await self._retrieve_exact(
                            exact_retrieve,
                            terms,
                            limit,
                            None,
                            None,
                            None,
                        ),
                        limit,
                    )
                except Exception as exc:
                    self.last_trace["exact_global_error"] = type(exc).__name__

        if sparse:
            result = self._rrf_merge(
                [("exact", exact), ("dense", semantic), ("sparse", sparse)],
                limit,
            )
            self.last_strategy = "HYBRID_RRF"
        elif exact:
            result = self._merge(exact, semantic, limit)
            self.last_strategy = "HYBRID_EXACT_VECTOR"
        else:
            result = semantic
            self.last_strategy = "VECTOR"

        if self.reranker is not None and result:
            result = await self._apply_reranker(query, result, limit)
            self.last_strategy += "_RERANK"
        self.last_trace.update(
            {
                "dense_count": len(semantic),
                "sparse_count": len(sparse),
                "exact_count": len(exact),
                "sparse_error": sparse_error,
                "global_error": semantic_global_error,
                "sparse_global_error": sparse_global_error,
                "strategy": self.last_strategy,
            }
        )
        return self._approved_unique(result)[:limit]

    async def _retrieve_with_scope(
        self,
        backend,
        query: str,
        limit: int,
        concept_id: str | None,
        stage_id: str | None,
        concept_codes: list[str] | None,
    ) -> tuple[list[RetrievedDocument], str | None]:
        scoped = self._approved_unique(
            await self._backend_retrieve(
                backend,
                query,
                limit,
                concept_id,
                stage_id,
                concept_codes,
            )
        )
        if not (concept_id or stage_id or concept_codes):
            return scoped[:limit], None

        try:
            global_candidates = self._approved_unique(
                await self._backend_retrieve(
                    backend, query, max(limit, min(50, limit * 3)), None, None, None
                )
            )
            global_documents = [
                document
                for document in global_candidates
                if (document.knowledge_scope or "").casefold() == "global"
            ]
            return self._merge(scoped, global_documents, limit), None
        except Exception as exc:
            # Scoped evidence remains usable when optional global fallback is
            # unavailable. The trace contains only the safe exception type.
            return scoped[:limit], type(exc).__name__

    @staticmethod
    async def _backend_retrieve(
        backend,
        query: str,
        limit: int,
        concept_id: str | None,
        stage_id: str | None,
        concept_codes: list[str] | None,
    ) -> list[RetrievedDocument]:
        try:
            return await backend.retrieve(
                query,
                limit,
                concept_id=concept_id,
                stage_id=stage_id,
                concept_codes=concept_codes,
            )
        except TypeError:
            return await backend.retrieve(
                query,
                limit,
                concept_id=concept_id,
                stage_id=stage_id,
            )

    def _approved_unique(
        self, documents: list[RetrievedDocument]
    ) -> list[RetrievedDocument]:
        approved = [
            document
            for document in documents
            if document.review_status == self.approved_status
        ]
        return self._merge(approved, [], len(approved))

    def _rrf_merge(
        self,
        ranked_lists: list[tuple[str, list[RetrievedDocument]]],
        limit: int,
    ) -> list[RetrievedDocument]:
        scores: dict[tuple[str, str], float] = {}
        documents: dict[tuple[str, str], RetrievedDocument] = {}
        for _, ranked in ranked_lists:
            for rank, document in enumerate(ranked, start=1):
                key = document.citation_key()
                scores[key] = scores.get(key, 0.0) + 1.0 / (self.fusion_k + rank)
                documents.setdefault(key, document)
        if not scores:
            return []
        max_score = max(scores.values())
        ordered = sorted(scores, key=lambda key: scores[key], reverse=True)[:limit]
        return [
            replace(
                documents[key],
                score=round(scores[key] / max_score, 6),
                retrieval_method="hybrid",
            )
            for key in ordered
        ]

    async def _apply_reranker(
        self, query: str, documents: list[RetrievedDocument], limit: int
    ) -> list[RetrievedDocument]:
        rerank = getattr(self.reranker, "rerank", None)
        if rerank is None:
            return documents[:limit]
        ranked = rerank(query, documents)
        if hasattr(ranked, "__await__"):
            ranked = await ranked
        return list(ranked)[:limit]

    async def retrieve_related(
        self,
        documents: list[RetrievedDocument],
        concept_id: str | None = None,
        stage_id: str | None = None,
        concept_codes: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
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
        return self._merge(documents, related, self.last_limit)

    @staticmethod
    async def _retrieve_exact(
        exact_retrieve,
        terms: list[str],
        top_k: int,
        concept_id: str | None,
        stage_id: str | None,
        concept_codes: list[str] | None,
    ):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
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
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
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


def _surface_match(left: str, right: str) -> bool:
    """Match common Korean surface variants without claiming full stemming."""
    if left == right:
        return True
    if not (re.fullmatch(r"[가-힣]+", left) and re.fullmatch(r"[가-힣]+", right)):
        return False
    shorter, longer = sorted((left, right), key=len)
    return len(shorter) >= 2 and longer.startswith(shorter)
