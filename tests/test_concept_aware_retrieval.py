from __future__ import annotations

import pytest

from app.core.exceptions import RetrievalError
from app.evaluation.rag_metrics import evaluate_retrieval
from app.rag.retrieval.retriever import InMemoryRetriever, Retriever
from app.rag.retrieval.types import RetrievedDocument


def doc(
    document_id: str,
    content: str,
    *,
    concept_code: str | None = None,
    knowledge_scope: str = "scoped",
    review_status: str = "approved",
    chunk_id: str | None = None,
) -> RetrievedDocument:
    return RetrievedDocument(
        content=content,
        source="fixture",
        document_id=document_id,
        chunk_id=chunk_id or f"{document_id}:0",
        title=document_id,
        concept_code=concept_code,
        knowledge_scope=knowledge_scope,
        review_status=review_status,
    )


@pytest.mark.asyncio
async def test_concept_code_mapping_filters_unapproved_and_deduplicates_by_citation():
    scoped = doc("mapped", "기준금리와 대출금리의 관계", concept_code="C-RATE")
    duplicate = doc(
        "mapped",
        "기준금리와 대출금리의 관계 복제 청크",
        concept_code="C-RATE",
    )
    wrong_concept = doc("other", "기준금리 설명", concept_code="C-OTHER")
    draft = doc(
        "draft",
        "기준금리 검수 전 문서",
        concept_code="C-RATE",
        review_status="draft",
    )
    results = await Retriever(
        InMemoryRetriever([scoped, duplicate, wrong_concept, draft]), top_k=5
    ).retrieve("기준금리", concept_codes=["C-RATE"])

    assert [item.document_id for item in results] == ["mapped"]
    assert all(item.review_status == "approved" for item in results)


@pytest.mark.asyncio
async def test_global_knowledge_is_fallback_for_scoped_concept_and_stays_bounded():
    global_doc = doc(
        "global-rate",
        "기준금리는 중앙은행의 정책금리입니다.",
        knowledge_scope="global",
    )
    unrelated_scoped = doc(
        "other-scoped",
        "기준금리의 다른 설명",
        concept_code="C-OTHER",
    )
    retriever = Retriever(
        InMemoryRetriever([unrelated_scoped, global_doc]), top_k=1
    )

    results = await retriever.retrieve("기준금리", concept_codes=["C-MISSING"])

    assert [item.document_id for item in results] == ["global-rate"]
    assert len(results) == 1


@pytest.mark.asyncio
async def test_duplicate_chunks_are_removed_and_top_k_is_applied_after_hybrid_search():
    first = doc("same", "기준금리 정의", chunk_id="same:0")
    duplicate = doc("same", "기준금리 정의의 다른 검색 결과", chunk_id="same:0")
    second = doc("second", "기준금리와 대출금리")

    class Backend:
        async def retrieve(self, query, top_k=5, **kwargs):
            return [first, duplicate, second][:top_k]

    results = await Retriever(Backend(), top_k=1).retrieve("기준금리")

    assert len(results) == 1
    assert results[0].citation_key() == ("same", "same:0")


@pytest.mark.asyncio
async def test_dense_search_failure_is_normalized_for_api_error_handling():
    class FailingBackend:
        async def retrieve(self, *args, **kwargs):
            raise RuntimeError("database details must not escape")

    with pytest.raises(RetrievalError, match="retrieval failed"):
        await Retriever(FailingBackend()).retrieve("기준금리")


@pytest.mark.asyncio
async def test_no_approved_evidence_returns_empty_results_without_guessing():
    results = await Retriever(
        InMemoryRetriever(
            [doc("draft", "기준금리 초안", review_status="needs_review")]
        )
    ).retrieve("기준금리")

    assert results == []


def test_recall_at_k_comparison_uses_same_reviewed_relevance_set():
    baseline = evaluate_retrieval(
        [
            (["wrong", "mapped"], {"mapped"}),
            (["noise"], {"global-rate"}),
        ],
        k=1,
    )
    concept_aware = evaluate_retrieval(
        [
            (["mapped"], {"mapped"}),
            (["global-rate"], {"global-rate"}),
        ],
        k=1,
    )

    assert concept_aware.evaluated_queries == baseline.evaluated_queries
    assert concept_aware.recall_at_k > baseline.recall_at_k
