from __future__ import annotations

import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.dependencies import get_tutor_service, require_internal_api
from app.main import app
from app.rag.memory.concept_graph import ConceptGraphContextBuilder
from app.rag.memory.context_builder import ContextBuilder
from app.rag.memory.history_manager import HistoryManager
from app.rag.pipeline import MultiTurnRAG
from app.rag.retrieval.retriever import InMemoryRetriever, Retriever
from app.rag.retrieval.types import RetrievedDocument
from app.schemas.tutor import (
    ConceptGraphContext,
    InternalTutorRequest,
    PersonalizedTutorContext,
    VerifiedTutorContext,
)
from app.services.tutor_service import TutorService


def graph_payload(**overrides):
    value = {
        "currentConceptCode": "ECON_RATE",
        "prerequisiteConcepts": [
            {
                "conceptCode": "ECON_MONEY",
                "relationshipType": "PREREQUISITE",
                "relationReviewStatus": "approved",
                "depth": 1,
            },
            {
                "conceptCode": "ECON_POLICY",
                "relationshipType": "PREREQUISITE",
                "relationReviewStatus": "approved",
                "depth": 2,
            },
        ],
        "relatedConcepts": [],
        "learnerConceptMastery": {"ECON_MONEY": 0.8},
    }
    value.update(overrides)
    return value


def personalized_payload(**overrides):
    value = {
        "learnerProfile": {
            "conceptCode": "ECON_RATE",
            "accuracyRate": 0.7,
            "recentIncorrectCount": 2,
            "estimatedMastery": 0.55,
            "weaknessScore": 0.45,
            "currentStageId": "stage-1",
        },
        "misconceptionHypotheses": [
            {
                "hypothesisType": "RELATION_ERROR",
                "status": "UNCONFIRMED",
                "conceptCode": "ECON_RATE",
                "evidenceIds": ["assessment-1"],
            }
        ],
        "diagnosisEvidence": [],
        "recentAssessments": [],
        "teachingStrategy": None,
        "conceptGraphContext": graph_payload(),
    }
    value.update(overrides)
    return value


def test_personalized_schema_supports_camel_case_and_forbids_unknown_fields():
    context = PersonalizedTutorContext.model_validate(personalized_payload())
    assert context.learner_profile.estimated_mastery == 0.55
    assert context.concept_graph_context.current_concept_code == "ECON_RATE"

    with pytest.raises(ValidationError):
        PersonalizedTutorContext.model_validate(
            {**personalized_payload(), "unexpected": "value"}
        )
    with pytest.raises(ValidationError):
        PersonalizedTutorContext.model_validate(
            {
                **personalized_payload(),
                "learnerProfile": {"accuracyRate": 1.5},
            }
        )
    with pytest.raises(ValidationError):
        ConceptGraphContext.model_validate(
            graph_payload(learnerConceptMastery={"ECON_MONEY": 1.5})
        )


def test_old_internal_request_remains_valid_without_personalized_context():
    request = InternalTutorRequest.model_validate(
        {
            "requestId": str(uuid.uuid4()),
            "conversationId": str(uuid.uuid4()),
            "userId": str(uuid.uuid4()),
            "question": "기준금리가 뭐야?",
            "modelTier": "BASIC",
            "history": [],
            "context": None,
            "knowledgeScope": {"conceptCodes": []},
        }
    )
    assert request.personalized_context is None


def test_graph_builder_filters_unreviewed_cycles_duplicates_and_depth():
    graph = ConceptGraphContext.model_validate(
        graph_payload(
            prerequisiteConcepts=[
                {
                    "conceptCode": "ECON_MONEY",
                    "relationshipType": "PREREQUISITE",
                    "relationReviewStatus": "approved",
                    "depth": 1,
                },
                {
                    "conceptCode": "ECON_RATE",
                    "relationshipType": "PREREQUISITE",
                    "relationReviewStatus": "approved",
                    "depth": 1,
                },
                {
                    "conceptCode": "UNREVIEWED",
                    "relationshipType": "RELATED",
                    "relationReviewStatus": "pending",
                    "depth": 1,
                },
                {
                    "conceptCode": "TOO_DEEP",
                    "relationshipType": "PREREQUISITE",
                    "relationReviewStatus": "approved",
                    "depth": 3,
                },
            ],
            relatedConcepts=[
                {
                    "conceptCode": "ECON_MONEY",
                    "relationshipType": "RELATED",
                    "relationReviewStatus": "approved",
                    "depth": 1,
                }
            ],
        )
    )
    selection = ConceptGraphContextBuilder(max_depth=2).build(graph)

    assert selection is not None
    assert [node.concept_code for node in selection.nodes] == ["ECON_MONEY"]
    assert "UNREVIEWED" not in selection.text
    assert "TOO_DEEP" not in selection.text


def test_graph_builder_applies_node_and_token_bounds():
    nodes = [
        {
            "conceptCode": f"ECON_{index}",
            "relationshipType": "RELATED",
            "relationReviewStatus": "approved",
            "depth": 1,
        }
        for index in range(5)
    ]
    graph = ConceptGraphContext.model_validate(
        graph_payload(prerequisiteConcepts=nodes)
    )
    selection = ConceptGraphContextBuilder(max_nodes=2, max_tokens=100).build(graph)
    assert selection is not None
    assert len(selection.nodes) == 2
    assert len(selection.text) <= 400


def test_context_builder_omits_graph_when_no_relation_is_reviewed():
    context = ContextBuilder().build(
        history=[],
        retrieved_context=[],
        current_question="기준금리가 뭐야?",
        personalized_context=PersonalizedTutorContext.model_validate(
            personalized_payload(
                conceptGraphContext=graph_payload(
                    prerequisiteConcepts=[
                        {
                            "conceptCode": "UNREVIEWED",
                            "relationshipType": "PREREQUISITE",
                            "relationReviewStatus": "pending",
                            "depth": 1,
                        }
                    ],
                    relatedConcepts=[],
                )
            )
        ),
    )
    assert "검수된 개념 그래프" not in context.text
    assert "UNREVIEWED" not in context.text


def test_context_builder_prioritizes_question_and_evidence_over_history():
    document = RetrievedDocument(
        content="기준금리는 중앙은행의 정책금리입니다.",
        source="fixture",
        document_id="DOC-RATE",
        chunk_id="DOC-RATE:1",
    )
    context = ContextBuilder(max_tokens=100).build(
        history=[{"role": "user", "content": "오래된 대화" * 100}],
        retrieved_context=[document],
        current_question="기준금리가 뭐야?",
        rewritten_query="기준금리 정의",
        personalized_context=PersonalizedTutorContext.model_validate(
            personalized_payload()
        ),
    )
    assert "기준금리가 뭐야?" in context.text
    assert "DOC-RATE" in context.text
    assert "오래된 대화" not in context.text
    assert len(context.text) <= 420


@pytest.mark.asyncio
async def test_context_builder_isolation_for_concurrent_users_and_20_turn_history():
    builder = ContextBuilder(max_tokens=300)
    contexts = await asyncio.gather(
        asyncio.to_thread(
            builder.build,
            history=[
                {"role": "user", "content": f"user-a-{index}"}
                for index in range(20)
            ],
            retrieved_context=[],
            current_question="질문 A",
            personalized_context=PersonalizedTutorContext.model_validate(
                personalized_payload()
            ),
        ),
        asyncio.to_thread(
            builder.build,
            history=[
                {"role": "user", "content": f"user-b-{index}"}
                for index in range(20)
            ],
            retrieved_context=[],
            current_question="질문 B",
            personalized_context=PersonalizedTutorContext.model_validate(
                personalized_payload(
                    learnerProfile={"conceptCode": "ECON_INFLATION"},
                    conceptGraphContext=None,
                )
            ),
        ),
    )
    assert "질문 A" in contexts[0].text and "질문 B" not in contexts[0].text
    assert "질문 B" in contexts[1].text and "질문 A" not in contexts[1].text
    assert "ECON_RATE" in contexts[0].text
    assert "ECON_INFLATION" in contexts[1].text


class CaptureGenerator:
    llm = object()
    model_id = "test-model"
    last_usage = None

    def __init__(self):
        self.context = None

    async def generate(self, query, context):
        self.context = context
        return "근거 설명 [출처: DOC-RATE/DOC-RATE:1]"


def test_internal_api_accepts_optional_personalized_context():
    generator = CaptureGenerator()
    pipeline = MultiTurnRAG(
        history_manager=HistoryManager(),
        retriever=Retriever(
            InMemoryRetriever(
                [
                    RetrievedDocument(
                        content="기준금리 설명",
                        source="fixture",
                        document_id="DOC-RATE",
                        chunk_id="DOC-RATE:1",
                    )
                ]
            )
        ),
        answer_generator=generator,
    )
    service = TutorService(pipeline)
    request = {
        "requestId": str(uuid.uuid4()),
        "conversationId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()),
        "question": "기준금리가 뭐야?",
        "modelTier": "BASIC",
        "history": [],
        "context": None,
        "knowledgeScope": {"conceptCodes": []},
        "personalizedContext": personalized_payload(),
    }
    app.dependency_overrides[get_tutor_service] = lambda: service
    app.dependency_overrides[require_internal_api] = lambda: None
    try:
        response = TestClient(app).post("/internal/v1/tutor/answer", json=request)
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert generator.context is not None
    assert "ECON_MONEY" in generator.context.text


def test_openapi_exposes_personalized_context_with_camel_case_alias():
    schema = TestClient(app).get("/openapi.json").json()
    request_schema = schema["components"]["schemas"]["InternalTutorRequest"]
    assert "personalizedContext" in request_schema["properties"]
    assert "PersonalizedTutorContext" in str(
        request_schema["properties"]["personalizedContext"]
    )


def test_verified_context_is_optional_and_keeps_backend_block_reason():
    request = InternalTutorRequest.model_validate(
        {
            "requestId": str(uuid.uuid4()),
            "conversationId": str(uuid.uuid4()),
            "userId": str(uuid.uuid4()),
            "question": "기준금리가 뭐야?",
            "modelTier": "BASIC",
            "verifiedContext": {
                "verificationStatus": "BLOCKED",
                "conceptCode": "ECON_RATE",
                "blockingReasons": ["LICENSE_REVIEW_NOT_APPROVED:doc-1"],
            },
        }
    )
    assert request.verified_context.verification_status == "BLOCKED"
    assert request.verified_context.blocking_reasons


@pytest.mark.asyncio
async def test_verified_context_filters_retrieval_to_backend_source_ids():
    generator = CaptureGenerator()
    pipeline = MultiTurnRAG(
        history_manager=HistoryManager(),
        retriever=Retriever(
            InMemoryRetriever(
                [
                    RetrievedDocument(
                        content="승인된 기준금리 자료",
                        source="fixture",
                        document_id="DOC-APPROVED",
                        chunk_id="DOC-APPROVED:1",
                    ),
                    RetrievedDocument(
                        content="다른 개념 자료",
                        source="fixture",
                        document_id="DOC-OTHER",
                        chunk_id="DOC-OTHER:1",
                    ),
                ]
            )
        ),
        answer_generator=generator,
    )
    result = await pipeline.run_external(
        user_id="user-a",
        conversation_id="conversation-a",
        message="기준금리가 뭐야?",
        history=[],
        verified_context=VerifiedTutorContext(
            verificationStatus="VERIFIED",
            conceptCode="ECON_RATE",
            sourceDocumentIds=["DOC-APPROVED"],
        ),
    )
    assert [item.document_id for item in result.retrieved_documents] == ["DOC-APPROVED"]
    assert "DOC-OTHER" not in generator.context.text


@pytest.mark.asyncio
async def test_blocked_verified_context_holds_answer_without_generation():
    generator = CaptureGenerator()
    pipeline = MultiTurnRAG(
        history_manager=HistoryManager(),
        retriever=Retriever(InMemoryRetriever([])),
        answer_generator=generator,
    )
    result = await pipeline.run_external(
        user_id="user-a",
        conversation_id="conversation-a",
        message="기준금리가 뭐야?",
        history=[],
        verified_context=VerifiedTutorContext(
            verificationStatus="BLOCKED",
            conceptCode="ECON_RATE",
            blockingReasons=["CONCEPT_REVIEW_HISTORY_MISSING"],
        ),
    )
    assert result.grounded is False
    assert result.citations == []
    assert generator.context is None
