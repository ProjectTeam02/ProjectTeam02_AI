from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from app.api.dependencies import get_tutor_service, require_internal_api
from app.db import postgres
from app.main import app
from app.rag.generation.answer_generator import AnswerGenerator
from app.rag.memory.history_manager import HistoryManager
from app.rag.pipelines.multiturn_rag import MultiTurnRAG
from app.rag.retrieval.retriever import InMemoryRetriever, Retriever
from app.rag.retrieval.types import RetrievedDocument
from app.services.tutor_service import TutorService


def rate_document(concept_code: str | None = None) -> RetrievedDocument:
    return RetrievedDocument(
        content="기준금리가 오르면 대출금리 상승 압력이 생길 수 있습니다.",
        source="fixture",
        source_id="SRC-RATE",
        document_id="DOC-RATE",
        chunk_id="DOC-RATE:1",
        title="기준금리 학습자료",
        version="v1",
        concept_code=concept_code,
        review_status="approved",
    )


class FakeGenerator:
    llm = object()
    model_id = "test-model"
    last_usage = {"prompt_tokens": 12, "completion_tokens": 8}

    async def generate(self, query, context):
        return (
            "기준금리가 오르면 대출금리 상승 압력이 생길 수 있습니다. "
            "[출처: DOC-RATE/DOC-RATE:1]"
        )


def service(documents=None, generator=None) -> TutorService:
    pipeline = MultiTurnRAG(
        history_manager=HistoryManager(),
        retriever=Retriever(InMemoryRetriever(documents or [rate_document()])),
        answer_generator=generator or FakeGenerator(),
    )
    return TutorService(pipeline)


def payload(**overrides):
    value = {
        "requestId": str(uuid.uuid4()),
        "conversationId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()),
        "question": "기준금리가 뭐야?",
        "modelTier": "BASIC",
        "history": [],
        "summary": None,
        "summaryUntilSeq": None,
        "context": None,
        "knowledgeScope": {"conceptCodes": []},
    }
    value.update(overrides)
    return value


def post_with_service(request, tutor_service):
    app.dependency_overrides[get_tutor_service] = lambda: tutor_service
    app.dependency_overrides[require_internal_api] = lambda: None
    try:
        return TestClient(app).post("/internal/v1/tutor/answer", json=request)
    finally:
        app.dependency_overrides.clear()


def test_internal_api_uses_external_history_and_does_not_persist_backend_tables():
    tutor_service = service()
    first_request = payload()
    first = post_with_service(first_request, tutor_service)
    assert first.status_code == 200

    second_request = payload(
        conversationId=first_request["conversationId"],
        question="그게 오르면 대출을 받은 사람에게 어떤 영향이 있어?",
        history=[
            {
                "sequenceNo": 1,
                "role": "USER",
                "content": "기준금리가 뭐야?",
            },
            {
                "sequenceNo": 2,
                "role": "ASSISTANT",
                "content": "중앙은행의 정책금리야.",
            },
        ],
    )
    second = post_with_service(second_request, tutor_service)
    body = second.json()

    assert second.status_code == 200
    assert "기준금리" in body["rewrittenQuery"]
    assert body["historyFromSeq"] == 1
    assert body["groundingStatus"] == "GROUNDED"
    assert tutor_service.pipeline.history_manager.repository._conversations == {}


def test_internal_api_rejects_invalid_uuid_enum_and_history_sequence():
    invalid_uuid = post_with_service(payload(requestId="not-a-uuid"), service())
    assert invalid_uuid.status_code == 422

    invalid_tier = post_with_service(payload(modelTier="PREMIUM"), service())
    assert invalid_tier.status_code == 422

    invalid_history = post_with_service(
        payload(
            history=[
                {"sequenceNo": 2, "role": "USER", "content": "a"},
                {"sequenceNo": 1, "role": "ASSISTANT", "content": "b"},
            ]
        ),
        service(),
    )
    assert invalid_history.status_code == 422


def test_internal_api_returns_insufficient_without_search_evidence():
    response = post_with_service(payload(question="화성 날씨"), service(documents=[]))
    assert response.status_code == 200
    body = response.json()
    assert body["groundingStatus"] == "INSUFFICIENT"
    assert body["sources"] == []
    assert body["usage"]["retrievalStrategy"] == "NONE"


def test_internal_api_does_not_return_offline_answer_as_production_success():
    response = post_with_service(
        payload(),
        service(generator=AnswerGenerator(llm=None)),
    )
    assert response.status_code == 503


def test_internal_api_applies_knowledge_scope():
    response = post_with_service(
        payload(knowledgeScope={"conceptCodes": ["other-concept"]}),
        service(documents=[rate_document(concept_code="rate-concept")]),
    )
    assert response.status_code == 200
    assert response.json()["groundingStatus"] == "INSUFFICIENT"
    assert response.json()["sources"] == []


def test_internal_api_openapi_exposes_contract_enums():
    schema = TestClient(app).get("/openapi.json").json()
    request_schema = schema["components"]["schemas"]["InternalTutorRequest"]
    response_schema = schema["components"]["schemas"]["InternalTutorResponse"]
    assert request_schema["properties"]["modelTier"]["$ref"].endswith("ModelTier")
    assert "groundingStatus" in response_schema["properties"]


def test_create_tables_excludes_node_owned_erd_tables(monkeypatch):
    captured = {}

    class FakeConnection:
        async def run_sync(self, function, **kwargs):
            captured["tables"] = kwargs["tables"]

    class BeginContext:
        async def __aenter__(self):
            return FakeConnection()

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    class FakeEngine:
        def begin(self):
            return BeginContext()

    monkeypatch.setattr(postgres, "_engine", FakeEngine())
    asyncio.run(postgres.create_tables())

    names = {table.name for table in captured["tables"]}
    assert names == {
        "ai_user_memories",
        "rag_documents",
        "rag_document_chunks",
        "rag_index_configurations",
    }


def test_external_history_builder_includes_summary_and_respects_cutoff():
    manager = HistoryManager(max_messages=4, max_tokens=100)
    history, history_from_seq = manager.from_external(
        conversation_id=str(uuid.uuid4()),
        user_id=str(uuid.uuid4()),
        messages=[
            {"sequenceNo": 1, "role": "USER", "content": "old"},
            {"sequenceNo": 2, "role": "ASSISTANT", "content": "old answer"},
            {"sequenceNo": 3, "role": "USER", "content": "new question"},
        ],
        summary="기준금리의 정의 요약",
        summary_until_seq=2,
    )
    assert [item.role for item in history.messages] == ["summary", "user"]
    assert history.messages[-1].sequence_no == 3
    assert history_from_seq == 3
