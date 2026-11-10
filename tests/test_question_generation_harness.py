from __future__ import annotations

import asyncio
import uuid

from fastapi.testclient import TestClient

from app.api.dependencies import (
    get_question_job_service,
    require_internal_api,
)
from app.core.config import Settings
from app.main import app
from app.question_generation.evidence import EvidenceSource, JsonlEvidenceProvider
from app.question_generation.jobs import (
    InMemoryQuestionJobRepository,
    QuestionGenerationJobService,
)
from app.question_generation.service import QuestionGenerationService
from app.schemas.question_generation import GenerationRequest


class FakeLLM:
    def __init__(self, *responses: dict):
        self.responses = list(responses)
        self.calls = []
        self.model_id = "mock-qg-model"

    async def complete_json(self, *, system_prompt: str, user_payload: dict):
        self.calls.append({"system": system_prompt, "payload": user_payload})
        return self.responses.pop(0)


class StaticEvidence:
    def __init__(self, sources):
        self.sources = sources

    async def search(self, request):
        return self.sources


def question_response():
    return {
        "questionType": "CONCEPT",
        "question": "물가상승률의 의미로 가장 적절한 것은 무엇인가?",
        "choices": [
            "일정 기간 물가 수준의 변동률",
            "실업률의 수준",
            "환율의 고정값",
            "국민소득의 총액",
        ],
        "correctAnswerIndex": 0,
        "explanation": "물가상승률은 일정 기간 물가 수준의 변동률이다.",
        "learningObjective": "물가상승률의 의미를 설명한다",
        "sourceIds": ["BOK-1"],
    }


def generation_response():
    return {
        "topic": "인플레이션",
        "difficulty": "MEDIUM",
        "questions": [question_response()],
    }


def evidence():
    return [
        EvidenceSource(
            source_id="BOK-1",
            document_id="BOK-DOC-1",
            document_version="2026-01",
            content="물가상승률은 일정 기간 물가 수준의 변동률이다.",
            review_status="approved",
        )
    ]


def job_service(fake: FakeLLM, sources=None, revisions=2):
    generator = QuestionGenerationService(
        settings=Settings(
            internal_api_token="test",
            question_max_count=20,
            question_max_revision_attempts=revisions,
        ),
        llm=fake,
        evidence_provider=StaticEvidence(evidence() if sources is None else sources),
    )
    return QuestionGenerationJobService(generator, InMemoryQuestionJobRepository())


def request(request_id=None):
    return {
        "requestId": str(request_id or uuid.uuid4()),
        "chapterId": "macro",
        "topic": "인플레이션",
        "difficulty": "MEDIUM",
        "questionCount": 1,
        "learningObjectives": ["물가상승률의 의미를 설명한다"],
    }


def call_job(service, body):
    app.dependency_overrides[get_question_job_service] = lambda: service
    app.dependency_overrides[require_internal_api] = lambda: None
    try:
        return TestClient(app).post("/internal/v1/questions/jobs", json=body)
    finally:
        app.dependency_overrides.clear()


def test_success_job_is_pending_review_and_tracks_document_version():
    service = job_service(
        FakeLLM(
            generation_response(),
            {
                "decision": "APPROVE",
                "independentAnswerIndex": 0,
                "issues": [],
                "feedback": "",
            },
        )
    )
    body = call_job(service, request()).json()

    assert body["executionStatus"] == "COMPLETED"
    assert body["reviewStatus"] == "PENDING_REVIEW"
    assert body["result"]["evidenceReferences"] == [
        {
            "sourceId": "BOK-1",
            "documentId": "BOK-DOC-1",
            "documentVersion": "2026-01",
        }
    ]
    app.dependency_overrides[get_question_job_service] = lambda: service
    app.dependency_overrides[require_internal_api] = lambda: None
    try:
        response = TestClient(app).get(f"/internal/v1/questions/jobs/{body['jobId']}")
        assert response.status_code == 200
        assert response.json()["result"]["questions"]
    finally:
        app.dependency_overrides.clear()


def test_missing_approved_evidence_fails_without_reviewable_questions():
    fake = FakeLLM()
    response = call_job(job_service(fake, sources=[]), request())
    body = response.json()

    assert response.status_code == 202
    assert body["executionStatus"] == "FAILED"
    assert body["failureStep"] == "evidence_lookup"
    assert body["failureCode"] == "INSUFFICIENT_EVIDENCE"
    assert body["result"] is None
    assert fake.calls == []


def test_same_request_id_is_idempotent_and_does_not_save_twice():
    fake = FakeLLM(
        generation_response(),
        {
            "decision": "APPROVE",
            "independentAnswerIndex": 0,
            "issues": [],
            "feedback": "",
        },
    )
    service = job_service(fake)
    body = request()

    first = call_job(service, body).json()
    second = call_job(service, body).json()

    assert first["jobId"] == second["jobId"]
    assert first["result"]["questions"] == second["result"]["questions"]
    assert len(fake.calls) == 2


def test_reusing_request_id_with_different_payload_is_rejected():
    fake = FakeLLM(
        generation_response(),
        {
            "decision": "APPROVE",
            "independentAnswerIndex": 0,
            "issues": [],
            "feedback": "",
        },
    )
    service = job_service(fake)
    body = request()
    assert call_job(service, body).status_code == 202

    changed = {**body, "topic": "환율"}
    response = call_job(service, changed)
    assert response.status_code == 409


def test_qv_revision_limit_is_two_after_initial_generation():
    revise = {
        "decision": "REVISE",
        "independentAnswerIndex": 0,
        "issues": ["조건이 불명확하다"],
        "feedback": "조건을 보강하라",
    }
    fake = FakeLLM(
        generation_response(),
        revise,
        generation_response(),
        revise,
        generation_response(),
        revise,
    )
    service = job_service(fake, revisions=2)
    body = call_job(service, request()).json()

    assert body["executionStatus"] == "FAILED"
    assert body["failureStep"] == "qv_or_code_validation"
    assert body["result"] is None
    assert len(fake.calls) == 6


def test_server_approval_allowlist_is_required_when_configured(tmp_path):
    evidence_path = tmp_path / "evidence.jsonl"
    approval_path = tmp_path / "approved.json"
    evidence_path.write_text(
        '{"source_id":"BOK-1","document_id":"DOC-1","document_version":"v1",'
        '"content":"인플레이션은 물가 상승이다.","review_status":"approved"}\n',
        encoding="utf-8",
    )
    approval_path.write_text(
        '[{"documentId":"DOC-1","reviewStatus":"approved"}]',
        encoding="utf-8",
    )
    provider = JsonlEvidenceProvider(evidence_path, approval_label_path=approval_path)
    generation_request = request()
    generation_request.pop("requestId")
    result = asyncio.run(
        provider.search(GenerationRequest.model_validate(generation_request))
    )
    assert [source.document_id for source in result] == ["DOC-1"]
