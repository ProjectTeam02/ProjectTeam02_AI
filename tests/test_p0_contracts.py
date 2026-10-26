from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_tutor_service, require_internal_api
from app.core.config import Settings
from app.evaluation.rag_metrics import compare_runs, evaluate_retrieval
from app.ingestion.document_loader import load_manifest
from app.main import app
from app.rag.generation.answer_generator import AnswerGenerator
from app.rag.grounding.citation_validator import CitationValidator
from app.rag.llamaindex.indexer import DocumentIndexer, IngestDocument
from app.rag.memory.history_manager import HistoryManager
from app.rag.pipelines.multiturn_rag import MultiTurnRAG
from app.rag.query.query_rewriter import QueryRewriter
from app.rag.retrieval.retriever import InMemoryRetriever, Retriever
from app.rag.retrieval.types import RetrievedDocument
from app.services.tutor_service import TutorService


def approved_rate_document() -> RetrievedDocument:
    return RetrievedDocument(
        content="기준금리가 오르면 일반적으로 대출금리의 상승 압력이 커질 수 있습니다.",
        source="https://example.test/rate",
        source_url="https://example.test/rate",
        source_id="SRC-RATE",
        document_id="DOC-RATE",
        chunk_id="DOC-RATE:1",
        title="기준금리 학습자료",
        version="v1",
        concept_id="concept-rate",
        stage_id="stage-rate",
        review_status="approved",
    )


def internal_service() -> TutorService:
    pipeline = MultiTurnRAG(
        history_manager=HistoryManager(),
        retriever=Retriever(InMemoryRetriever([approved_rate_document()])),
        answer_generator=AnswerGenerator(llm=None),
    )
    return TutorService(pipeline)


def test_internal_api_camel_case_contract_and_idempotency():
    service = internal_service()
    app.dependency_overrides[get_tutor_service] = lambda: service
    app.dependency_overrides[require_internal_api] = lambda: None
    payload = {
        "userId": "user-1",
        "conversationId": None,
        "requestId": "request-1",
        "stageId": "stage-rate",
        "conceptId": "concept-rate",
        "question": "기준금리가 오르면 어떻게 돼?",
    }
    try:
        client = TestClient(app)
        first = client.post("/internal/v1/tutor/answer", json=payload)
        second = client.post("/internal/v1/tutor/answer", json=payload)
        assert first.status_code == 200
        assert second.status_code == 200
        body = first.json()
        assert second.json() == body
        assert body["conversationId"]
        assert body["requestId"] == "request-1"
        assert body["grounded"] is True
        assert body["citations"][0] == {
            "sourceId": "SRC-RATE",
            "documentId": "DOC-RATE",
            "documentVersion": "v1",
            "title": "기준금리 학습자료",
            "url": "https://example.test/rate",
        }
    finally:
        app.dependency_overrides.clear()


def test_internal_api_rejects_missing_service_authentication():
    client = TestClient(app)
    response = client.post(
        "/internal/v1/tutor/answer",
        json={
            "userId": "user-1",
            "requestId": "request-auth",
            "stageId": "stage-rate",
            "conceptId": "concept-rate",
            "question": "기준금리가 뭐야?",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_rewriter_does_not_pollute_unrelated_short_question():
    history = [{"role": "user", "content": "기준금리가 뭐야?"}]
    rewritten = await QueryRewriter().rewrite("환율이 뭐야?", history)
    assert rewritten == "환율이 뭐야?"
    switched = await QueryRewriter().rewrite("그럼 환율이 뭐야?", history)
    assert switched == "그럼 환율이 뭐야?"


@pytest.mark.asyncio
async def test_retriever_filters_unapproved_and_concept_stage():
    approved = approved_rate_document()
    draft = RetrievedDocument(
        content="기준금리 초안",
        source="draft",
        document_id="DRAFT",
        chunk_id="DRAFT:1",
        concept_id="concept-rate",
        stage_id="stage-rate",
        review_status="draft",
    )
    retriever = Retriever(InMemoryRetriever([approved, draft]))
    results = await retriever.retrieve(
        "기준금리 상승", concept_id="concept-rate", stage_id="stage-rate"
    )
    assert [item.document_id for item in results] == ["DOC-RATE"]
    assert await retriever.retrieve("기준금리", concept_id="other") == []


def test_grounding_requires_claim_overlap_and_real_citation():
    source = approved_rate_document()
    validator = CitationValidator(min_overlap=0.2)
    unrelated = validator.validate_and_build(
        "화성에는 거대한 바다가 있습니다. [출처: DOC-RATE/DOC-RATE:1]", [source]
    )
    fabricated = validator.validate_and_build(
        "기준금리 설명입니다. [출처: OTHER/1]", [source]
    )
    assert unrelated.valid is True
    assert unrelated.grounded is False
    assert fabricated.valid is False
    assert fabricated.citations == []


@pytest.mark.asyncio
async def test_pipeline_removes_case_insensitive_fabricated_citation():
    class FabricatingGenerator:
        async def generate(self, query, context):
            return "근거 없는 답변 [Source: OTHER/unknown]"

    pipeline = MultiTurnRAG(
        history_manager=HistoryManager(),
        retriever=Retriever(InMemoryRetriever([approved_rate_document()])),
        answer_generator=FabricatingGenerator(),
    )
    result = await pipeline.run("user-1", "기준금리")
    assert "OTHER/unknown" not in result.answer
    assert result.citations == []
    assert result.grounded is False


def test_manifest_loader_requires_metadata_and_preserves_fields(tmp_path):
    (tmp_path / "rate.md").write_text("기준금리 설명\n\n\n검수 문서", encoding="utf-8")
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "documents": [
                    {
                        "path": "rate.md",
                        "source_id": "SRC-1",
                        "document_id": "DOC-1",
                        "document_version": "2026-01",
                        "title": "기준금리",
                        "source_url": "https://example.test/source",
                        "concept_id": "concept-1",
                        "stage_id": "stage-1",
                        "review_status": "approved",
                        "license": "test-only",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    document = load_manifest(manifest)[0]
    assert document.source_id == "SRC-1"
    assert document.version == "2026-01"
    assert document.content == "기준금리 설명\n\n검수 문서"


def test_retrieval_metrics_and_comparison():
    result = evaluate_retrieval([(["wrong", "right"], {"right"})], k=2)
    assert result.recall_at_k == 1.0
    assert result.mrr == 0.5
    comparison = compare_runs(
        [(["wrong"], {"right"})],
        [(["right"], {"right"})],
        k=1,
    )
    assert comparison["multi_turn"].mrr > comparison["single_turn"].mrr


@pytest.mark.asyncio
async def test_indexer_writes_metadata_and_replaces_old_nodes():
    class FakeVectorStore:
        def __init__(self):
            self.deleted: list[str] = []

        async def adelete_nodes(self, node_ids):
            self.deleted.extend(node_ids)

    class FakeIndex:
        def __init__(self):
            self.vector_store = FakeVectorStore()
            self.nodes = []

        async def ainsert_nodes(self, nodes):
            self.nodes.extend(nodes)

    class FakeManager:
        def __init__(self):
            self.index = FakeIndex()

        def get_or_create(self, collection):
            assert collection == "test_collection"
            return self.index

    class FakeRepository:
        def __init__(self):
            self.saved = []
            self.configuration = None

        async def ensure_index_configuration(self, *configuration):
            self.configuration = configuration

        async def existing_content_hashes(self, hashes):
            return set()

        async def chunk_ids_for_documents(self, document_ids):
            return ["old-node"]

        async def save_documents(self, documents, nodes, embedding_dimension):
            self.saved = [documents, nodes, embedding_dimension]

    settings = Settings(
        embedding_provider="deterministic",
        vector_store_collection="test_collection",
        chunk_size=256,
        chunk_overlap=0,
    )
    manager = FakeManager()
    repository = FakeRepository()
    indexer = DocumentIndexer(manager, settings, repository)
    count = await indexer.index(
        [
            IngestDocument(
                document_id="DOC-1",
                title="기준금리",
                source="https://example.test/source",
                source_id="SRC-1",
                source_url="https://example.test/source",
                content="기준금리는 중앙은행의 정책금리입니다.",
                version="v1",
                concept_id="concept-rate",
                stage_id="stage-rate",
                review_status="approved",
                license="test-only",
            )
        ]
    )
    assert count == len(manager.index.nodes) > 0
    assert manager.index.vector_store.deleted == ["old-node"]
    assert repository.configuration[-1] == settings.embedding_dimension
    assert manager.index.nodes[0].metadata["source_id"] == "SRC-1"
    assert repository.saved[0][0].content_hash


@pytest.mark.asyncio
async def test_indexer_rejects_unapproved_document_before_vector_write():
    settings = Settings(embedding_provider="deterministic")
    indexer = DocumentIndexer(settings=settings)
    with pytest.raises(ValueError, match="only approved"):
        await indexer.index(
            [
                IngestDocument(
                    document_id="DRAFT-1",
                    title="초안",
                    source="local",
                    content="검수 전 자료",
                    review_status="draft",
                )
            ]
        )
