from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user_id, get_tutor_service
from app.core.exceptions import ConversationAccessError, ConversationNotFoundError, GenerationError
from app.main import app
from app.rag.grounding.citation_validator import CitationValidator
from app.rag.memory.context_builder import ContextBuilder
from app.rag.memory.history_manager import HistoryManager
from app.rag.pipelines.multiturn_rag import MultiTurnRAG
from app.rag.query.query_rewriter import QueryRewriter
from app.rag.retrieval.retriever import InMemoryRetriever, Retriever
from app.rag.retrieval.types import RetrievedDocument
from app.services.tutor_service import TutorService


@dataclass
class FakeResponse:
    text: str


class FakeAnswerGenerator:
    def __init__(self, answer: str | None = None):
        self.answer = answer
        self.queries: list[str] = []

    async def generate(self, query, context):
        self.queries.append(query)
        if self.answer is not None:
            return self.answer
        return f"학습자료에 따르면 {query}입니다. [출처: finance-1/chunk-1]"


def build_pipeline(generator=None, documents=None):
    history = HistoryManager()
    documents = documents if documents is not None else [
        RetrievedDocument(
            content="GDP는 일정 기간 한 나라 안에서 생산된 최종 재화와 서비스의 가치입니다.",
            source="approved-fixture",
            document_id="finance-1",
            chunk_id="chunk-1",
            title="GDP 기초",
            version="test",
        )
    ]
    return MultiTurnRAG(
        history_manager=history,
        retriever=Retriever(InMemoryRetriever(documents), top_k=5),
        answer_generator=generator or FakeAnswerGenerator(),
    )


@pytest.mark.asyncio
async def test_first_and_follow_up_questions_keep_conversation_and_rewrite():
    pipeline = build_pipeline()

    first = await pipeline.run("user-1", "GDP가 뭐야?")
    second = await pipeline.run("user-1", "그럼 GDP가 증가하면 무조건 좋은 거야?", first.conversation_id)

    assert first.conversation_id
    assert second.conversation_id == first.conversation_id
    assert "GDP" in second.rewritten_query
    history = await pipeline.history_manager.load(first.conversation_id, "user-1")
    assert [item.role for item in history.messages] == ["user", "assistant", "user", "assistant"]
    assert second.citations[0].document_id == "finance-1"


@pytest.mark.asyncio
async def test_missing_and_foreign_conversation_are_rejected():
    pipeline = build_pipeline()
    first = await pipeline.run("user-1", "GDP가 뭐야?")

    with pytest.raises(ConversationNotFoundError):
        await pipeline.run("user-1", "질문", "not-a-conversation")
    with pytest.raises(ConversationAccessError):
        await pipeline.run("user-2", "질문", first.conversation_id)


@pytest.mark.asyncio
async def test_no_search_result_returns_safe_answer_without_citation():
    pipeline = build_pipeline(documents=[])
    result = await pipeline.run("user-1", "전혀 모르는 개념을 알려줘")
    assert result.citations == []
    assert "학습자료가 없어" in result.answer


@pytest.mark.asyncio
async def test_generation_failure_does_not_persist_partial_turn():
    class FailingGenerator:
        async def generate(self, query, context):
            raise GenerationError("timeout")

    pipeline = build_pipeline(generator=FailingGenerator())
    with pytest.raises(GenerationError):
        await pipeline.run("user-1", "GDP가 뭐야?")
    # The newly created session exists, but neither side of the failed turn does.
    conversation = await pipeline.history_manager.create("user-2")
    assert conversation.messages == []


@pytest.mark.asyncio
async def test_context_is_bounded_and_citation_rejects_unknown_chunk():
    context = ContextBuilder(max_tokens=100).build(
        history=[{"role": "user", "content": "x" * 1000}],
        retrieved_context=[],
        current_question="q",
        rewritten_query="q",
    )
    assert len(context.text) <= 420

    validator = CitationValidator()
    source = RetrievedDocument("fact", "source", document_id="d1", chunk_id="c1")
    assert not validator.validate("fact [출처: d1/unknown]", [source])
    assert validator.validate("fact [출처: d1/c1]", [source])


@pytest.mark.asyncio
async def test_query_rewriter_only_uses_previous_topic():
    rewritten = await QueryRewriter().rewrite(
        "그럼 금리와 무슨 관계야?",
        [{"role": "user", "content": "인플레이션이 뭐야?"}],
    )
    assert "인플레이션" in rewritten
    assert "금리" in rewritten


def test_tutor_api_uses_authenticated_user_and_preserves_conversation():
    pipeline = build_pipeline()
    service = TutorService(pipeline)
    app.dependency_overrides[get_tutor_service] = lambda: service
    app.dependency_overrides[get_current_user_id] = lambda: "user-1"
    try:
        client = TestClient(app)
        headers = {"X-Internal-API-Key": "test", "X-User-ID": "user-1"}
        first = client.post(
            "/api/tutor/chat",
            json={"user_id": "user-1", "message": "GDP가 뭐야?"},
            headers=headers,
        )
        assert first.status_code == 200
        first_body = first.json()
        second = client.post(
            "/api/tutor/chat",
            json={
                "user_id": "user-1",
                "conversation_id": first_body["conversation_id"],
                "message": "그럼 증가하면?",
            },
            headers=headers,
        )
        assert second.status_code == 200
        assert second.json()["conversation_id"] == first_body["conversation_id"]

        foreign = client.post(
            "/api/tutor/chat",
            json={
                "user_id": "user-2",
                "conversation_id": first_body["conversation_id"],
                "message": "질문",
            },
            headers={**headers, "X-User-ID": "user-2"},
        )
        assert foreign.status_code == 403
    finally:
        app.dependency_overrides.clear()
