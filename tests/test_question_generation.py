from __future__ import annotations

import asyncio
import json

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_question_generation_service
from app.core.config import Settings
from app.main import app
from app.question_generation.evidence import JsonlEvidenceProvider
from app.question_generation.service import QuestionGenerationService
from app.schemas.question_generation import EvidenceSource, GenerationRequest


class FakeLLM:
    def __init__(self, *responses: dict[str, object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def complete_json(
        self, *, system_prompt: str, user_payload: dict[str, object]
    ):
        self.calls.append({"system": system_prompt, "payload": user_payload})
        if not self.responses:
            raise AssertionError("unexpected LLM call")
        return self.responses.pop(0)


class StaticEvidence:
    def __init__(self, sources: list[EvidenceSource]) -> None:
        self.sources = sources

    async def search(self, request: GenerationRequest) -> list[EvidenceSource]:
        return self.sources


def request() -> GenerationRequest:
    return GenerationRequest(
        topic="인플레이션",
        difficulty="MEDIUM",
        questionCount=1,
        learningObjectives=["물가상승률의 의미를 설명한다"],
    )


def evidence() -> list[EvidenceSource]:
    return [
        EvidenceSource(
            source_id="BOK-1",
            document_id="DOC-1",
            document_version="2026-01",
            content="물가상승률은 일정 기간 물가 수준의 변동률이다.",
            review_status="approved",
        )
    ]


def generated_question(
    *, answer: int = 0, choice_two: str = "물가 수준의 변동률"
) -> dict[str, object]:
    return {
        "questionType": "CONCEPT",
        "question": "물가상승률의 의미로 가장 적절한 것은 무엇인가?",
        "choices": [choice_two, "실업률의 수준", "환율의 고정값", "국민소득의 총액"],
        "correctAnswerIndex": answer,
        "explanation": "물가상승률은 일정 기간 물가 수준이 얼마나 변했는지를 나타낸다.",
        "learningObjective": "물가상승률의 의미를 설명한다",
        "sourceIds": ["BOK-1"],
    }


def generation_response(question: dict[str, object]) -> dict[str, object]:
    return {
        "topic": "인플레이션",
        "difficulty": "MEDIUM",
        "questions": [question],
    }


def approved_response() -> dict[str, object]:
    return {
        "decision": "APPROVE",
        "independentAnswerIndex": 0,
        "issues": [],
        "feedback": "",
    }


def service_for(fake: FakeLLM, sources: list[EvidenceSource] | None = None):
    return QuestionGenerationService(
        settings=Settings(question_max_revision_attempts=1),
        llm=fake,
        evidence_provider=StaticEvidence(
            sources if sources is not None else evidence()
        ),
    )


@pytest.mark.asyncio
async def test_valid_batch_is_returned_only_after_independent_validation():
    fake = FakeLLM(generation_response(generated_question()), approved_response())

    result = await service_for(fake).generate(request())

    assert result.status == "COMPLETED"
    assert len(result.questions) == 1
    assert result.questions[0].correct_answer_index == 0
    assert result.source_ids == ["BOK-1"]
    assert result.prompt_versions == {"qg": "qg-v1", "qv": "qv-v1"}


@pytest.mark.asyncio
async def test_no_evidence_fails_before_any_llm_call():
    fake = FakeLLM()

    result = await service_for(fake, []).generate(request())

    assert result.status == "FAILED"
    assert result.error == "INSUFFICIENT_EVIDENCE"
    assert fake.calls == []


@pytest.mark.asyncio
async def test_model_conflicting_evidence_error_is_preserved():
    fake = FakeLLM(
        {
            "topic": "인플레이션",
            "difficulty": "MEDIUM",
            "questions": [],
            "error": "CONFLICTING_EVIDENCE",
        }
    )

    result = await service_for(fake).generate(request())

    assert result.status == "FAILED"
    assert result.error == "CONFLICTING_EVIDENCE"


@pytest.mark.asyncio
async def test_invalid_choices_never_reach_content_validation():
    question = generated_question()
    question["choices"] = ["같음", "같음", "다름", "기타"]
    fake = FakeLLM(generation_response(question))

    result = await service_for(fake).generate(request())

    assert result.status == "FAILED"
    assert result.error == "GENERATION_FAILED"
    assert len(fake.calls) == 1


@pytest.mark.asyncio
async def test_revise_is_generated_and_validated_again():
    revised = generated_question(choice_two="일정 기간 물가 수준의 변동률")
    fake = FakeLLM(
        generation_response(generated_question()),
        {
            "decision": "REVISE",
            "independentAnswerIndex": 0,
            "issues": ["조건을 더 명확히 작성해야 한다"],
            "feedback": "물가상승률의 기간을 문항에 명시하라",
        },
        generation_response(revised),
        approved_response(),
    )

    result = await service_for(fake).generate(request())

    assert result.status == "COMPLETED"
    assert len(result.validation) == 2
    assert result.validation[0].decision == "REVISE"
    assert result.validation[1].decision == "APPROVE"
    assert len(fake.calls) == 4


@pytest.mark.asyncio
async def test_independent_answer_mismatch_is_failure():
    fake = FakeLLM(
        generation_response(generated_question(answer=0)),
        {**approved_response(), "independentAnswerIndex": 1},
    )

    result = await service_for(fake).generate(request())

    assert result.status == "FAILED"
    assert result.error == "GENERATION_FAILED"
    assert result.questions == []


def test_jsonl_provider_returns_approved_matching_records_only(tmp_path):
    path = tmp_path / "evidence.jsonl"
    path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "source_id": "approved",
                        "document_id": "doc-a",
                        "document_version": "v1",
                        "content": "인플레이션은 물가 수준의 지속적인 상승이다.",
                        "review_status": "approved",
                    },
                    ensure_ascii=False,
                ),
                json.dumps(
                    {
                        "source_id": "pending",
                        "document_id": "doc-b",
                        "document_version": "v1",
                        "content": "인플레이션 관련 보류 자료",
                        "review_status": "needs_review",
                    },
                    ensure_ascii=False,
                ),
            ]
        ),
        encoding="utf-8",
    )

    provider = JsonlEvidenceProvider(path)
    results = asyncio.run(provider.search(request()))
    assert [item.source_id for item in results] == ["approved"]


def test_generation_route_requires_internal_auth(monkeypatch):
    import app.api.dependencies as dependencies

    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: Settings(internal_api_token="expected"),
    )
    client = TestClient(app)
    response = client.post(
        "/internal/v1/questions/generate",
        json={
            "topic": "인플레이션",
            "difficulty": "MEDIUM",
            "questionCount": 1,
            "learningObjectives": ["물가상승률의 의미를 설명한다"],
        },
    )
    assert response.status_code == 401


def test_generation_route_uses_internal_service(monkeypatch):
    import app.api.dependencies as dependencies

    fake = FakeLLM(generation_response(generated_question()), approved_response())
    service = service_for(fake)
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: Settings(internal_api_token="expected"),
    )
    app.dependency_overrides[get_question_generation_service] = lambda: service
    try:
        client = TestClient(app)
        response = client.post(
            "/internal/v1/questions/generate",
            headers={"X-Internal-API-Key": "expected"},
            json={
                "topic": "인플레이션",
                "difficulty": "MEDIUM",
                "questionCount": 1,
                "learningObjectives": ["물가상승률의 의미를 설명한다"],
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "COMPLETED"
    finally:
        app.dependency_overrides.pop(get_question_generation_service, None)


def test_question_generation_blocks_without_approved_evidence() -> None:
    from app.services.question_generation import prepare_question_generation

    plan = prepare_question_generation(
        concept_code="C0704",
        stage_id="R07_S04",
        learning_goal="개념 차이를 구별한다",
        blueprint=[{"type": "compare"}],
        evidence=[
            {
                "document_id": "bok-1",
                "content": "검토 대기 근거",
                "review_status": "needs_review",
            }
        ],
    )
    assert plan.status == "BLOCKED_NO_APPROVED_EVIDENCE"
    assert plan.prompt is None


def test_question_generation_prepares_draft_prompt_without_calling_model() -> None:
    from app.services.question_generation import prepare_question_generation

    plan = prepare_question_generation(
        concept_code="C0704",
        stage_id="R07_S04",
        learning_goal="개념 차이를 구별한다",
        blueprint=[{"type": "compare"}],
        evidence=[
            {
                "document_id": "bok-1",
                "content": "인플레이션은 물가수준이 지속적으로 상승하는 현상이다.",
                "review_status": "approved",
            }
        ],
    )
    assert plan.status == "DRAFT_READY"
    assert plan.evidence_document_ids == ("bok-1",)
    assert "bok-1" in (plan.prompt or "")
