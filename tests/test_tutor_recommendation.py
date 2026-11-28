from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.tutor import InternalTutorRequest
from app.services.tutor_recommendation import recommend


def payload(**overrides):
    value = {
        "requestId": str(uuid.uuid4()),
        "conversationId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()),
        "question": "개념을 다시 설명해줘",
        "modelTier": "BASIC",
        "history": [],
    }
    value.update(overrides)
    return value


def test_recommendation_selects_only_backend_candidate():
    request = InternalTutorRequest.model_validate(
        payload(
            context={"conceptCode": "ECON_RATE"},
            eligibleQuestionCandidates=[
                {
                    "questionId": "0b5e6a10-0000-4000-8000-000000000001",
                    "conceptCode": "OTHER",
                    "stageId": "0b5e6a10-0000-4000-8000-0000000000a1",
                    "attemptId": "0b5e6a10-0000-4000-8000-0000000000b1",
                },
                {
                    "questionId": "0b5e6a10-0000-4000-8000-000000000002",
                    "conceptCode": "ECON_RATE",
                    "stageId": "0b5e6a10-0000-4000-8000-0000000000a1",
                    "attemptId": "0b5e6a10-0000-4000-8000-0000000000b1",
                },
            ],
        )
    )

    _, action = recommend(request)

    assert action.type == "SOLVE_QUESTION"
    assert action.question_id == "0b5e6a10-0000-4000-8000-000000000002"
    assert action.question_id in {
        item.question_id for item in request.eligible_question_candidates
    }


def test_recommendation_without_candidates_falls_back_to_review():
    request = InternalTutorRequest.model_validate(
        payload(context={"conceptCode": "ECON_RATE"})
    )

    _, action = recommend(request)

    assert action.type == "REVIEW_CONCEPT"
    assert action.question_id is None


def test_single_wrong_answer_is_uncertain_and_has_no_fabricated_evidence():
    request = InternalTutorRequest.model_validate(
        payload(
            context={"conceptCode": "ECON_RATE"},
            personalizedContext={
                "misconceptionHypotheses": [
                    {
                        "hypothesisType": "CAUSAL_ERROR",
                        "status": "UNCONFIRMED",
                        "conceptCode": "ECON_RATE",
                        "evidenceIds": ["assessment-not-a-question"],
                        "confidence": 0.8,
                        "observationCount": 1,
                    }
                ],
                "diagnosisEvidence": [
                    {
                        "evidenceId": "assessment-1",
                        "evidenceType": "QUESTION_SUBMISSION",
                    }
                ],
            },
        )
    )

    meta, _ = recommend(request)

    assert meta.diagnosis.misconception_type == "UNCERTAIN"
    assert meta.diagnosis.confidence == 0
    assert meta.diagnosis.evidence_question_ids == []
    assert meta.diagnosis.needs_followup is True


def test_invalid_action_combinations_are_rejected():
    with pytest.raises(ValidationError):
        from app.schemas.tutor import ProposedAction

        ProposedAction(
            type="SOLVE_QUESTION",
            questionId="0b5e6a10-0000-4000-8000-000000000001",
            stageId=None,
            attemptId=None,
            reason="bad",
            priority="HIGH",
        )


def test_candidate_limit_and_duplicate_question_ids_are_rejected():
    candidate = {
        "questionId": "0b5e6a10-0000-4000-8000-000000000001",
        "conceptCode": "ECON_RATE",
        "stageId": "0b5e6a10-0000-4000-8000-0000000000a1",
        "attemptId": "0b5e6a10-0000-4000-8000-0000000000b1",
    }
    with pytest.raises(ValidationError):
        InternalTutorRequest.model_validate(
            payload(eligibleQuestionCandidates=[candidate] * 11)
        )
    with pytest.raises(ValidationError):
        InternalTutorRequest.model_validate(
            payload(eligibleQuestionCandidates=[candidate, candidate])
        )
