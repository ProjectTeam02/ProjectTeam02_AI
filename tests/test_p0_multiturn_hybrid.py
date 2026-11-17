from __future__ import annotations

import asyncio

import pytest

from app.core.exceptions import GenerationTimeoutError
from app.rag.harness import ExecutionHarness, StageContract
from app.rag.memory.history_manager import HistoryManager
from app.rag.pipeline import MultiTurnRAG
from app.rag.retrieval.reranker import LexicalReranker
from app.rag.retrieval.retriever import InMemoryRetriever, Retriever
from app.rag.retrieval.types import RetrievedDocument


def document(document_id: str, content: str, score: float | None = None):
    return RetrievedDocument(
        content=content,
        source="fixture",
        score=score,
        document_id=document_id,
        chunk_id=f"{document_id}:1",
        title=document_id,
        review_status="approved",
    )


class StaticBackend:
    def __init__(self, documents):
        self.documents = documents

    async def retrieve(self, query, top_k=5, **kwargs):
        return self.documents[:top_k]


@pytest.mark.asyncio
async def test_hybrid_rrf_keeps_documents_found_by_only_one_retriever():
    dense = StaticBackend([document("dense", "기준금리의 정의", 0.9)])
    sparse = StaticBackend([document("sparse", "대출금리와 기준금리의 관계", 0.8)])
    retriever = Retriever(
        dense,
        top_k=5,
        sparse_backend=sparse,
        fusion_k=1,
    )

    results = await retriever.retrieve("기준금리")

    assert {item.document_id for item in results} == {"dense", "sparse"}
    assert retriever.last_strategy == "HYBRID_RRF"
    assert retriever.last_trace["dense_count"] == 1
    assert retriever.last_trace["sparse_count"] == 1
    assert all(0.0 <= (item.score or 0.0) <= 1.0 for item in results)


@pytest.mark.asyncio
async def test_sparse_failure_falls_back_to_dense_without_leaking_error():
    class FailingBackend:
        async def retrieve(self, *args, **kwargs):
            raise RuntimeError("database details must not reach the answer")

    dense = StaticBackend([document("dense", "기준금리의 정의", 0.9)])
    retriever = Retriever(dense, sparse_backend=FailingBackend())

    results = await retriever.retrieve("기준금리")

    assert [item.document_id for item in results] == ["dense"]
    assert retriever.last_strategy == "VECTOR"
    assert retriever.last_trace["sparse_error"] == "RuntimeError"


@pytest.mark.asyncio
async def test_optional_deterministic_reranker_is_distinct_from_dense_order():
    first = document("first", "기준금리", 0.95)
    second = document("second", "대출금리 기준금리 상승 영향", 0.1)
    retriever = Retriever(
        StaticBackend([first, second]),
        reranker=LexicalReranker(),
    )

    results = await retriever.retrieve("대출금리 기준금리 상승 영향")

    assert results[0].document_id == "second"
    assert retriever.last_strategy == "VECTOR_RERANK"


@pytest.mark.asyncio
async def test_memory_decision_reports_summary_boundary_without_content():
    manager = HistoryManager(max_messages=2, max_tokens=100)
    history = await manager.create("user-1")
    await manager.append_turn(history.conversation_id, "user-1", "첫 질문", "첫 답변")
    await manager.append_turn(
        history.conversation_id, "user-1", "둘째 질문", "둘째 답변"
    )

    loaded = await manager.repository.get_owned(history.conversation_id, "user-1")
    decision = manager.memory_decision(loaded)

    assert decision.summary_required is True
    assert decision.summary_until_seq == 2
    assert decision.selected_message_count == 2
    assert not hasattr(decision, "content")


@pytest.mark.asyncio
async def test_ungrounded_generated_answer_is_held_and_trace_is_recorded():
    class UnsupportedGenerator:
        async def generate(self, query, context):
            return "금융시장에 관한 확인되지 않은 주장입니다. [출처: DOC/1]"

    source = document("DOC", "기준금리는 중앙은행의 정책금리입니다.")
    pipeline = MultiTurnRAG(
        history_manager=HistoryManager(),
        retriever=Retriever(InMemoryRetriever([source])),
        answer_generator=UnsupportedGenerator(),
    )

    result = await pipeline.run("user-1", "기준금리")

    assert result.grounded is False
    assert result.citations == []
    assert "충분히 검증하기 어려워요" in result.answer
    assert [event["stage"] for event in result.trace or []] == [
        "query_rewriting",
        "retrieval",
        "related_retrieval",
        "context",
        "answer_generation",
        "groundedness_validation",
    ]


@pytest.mark.asyncio
async def test_harness_retries_once_and_never_retries_forever():
    attempts = 0
    trace: list[dict[str, object]] = []

    async def flaky_operation():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("transient")
        return "ok"

    result = await ExecutionHarness(timeout_seconds=1, max_retries=1).run(
        StageContract("fixture", "input", "output"), flaky_operation, trace
    )

    assert result == "ok"
    assert attempts == 2
    assert [event["status"] for event in trace] == ["error", "ok"]

    async def hanging_operation():
        await asyncio.sleep(1)

    with pytest.raises(GenerationTimeoutError):
        await ExecutionHarness(timeout_seconds=0.01, max_retries=1).run(
            StageContract("timeout", "input", "output"),
            hanging_operation,
            [],
        )
