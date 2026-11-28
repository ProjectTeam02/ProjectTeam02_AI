"""Tutor FastAPI <-> Backend contract regression (docs/contract.md).

- JSON Schema snapshots in docs/contracts/ must match the Pydantic models.
- Golden valid examples must validate and round-trip byte-for-byte by alias.
- Golden invalid examples must be rejected (Backend rejects the same set;
  see scripts/check_backend_contract.sh).
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.schemas.tutor import InternalTutorRequest, InternalTutorResponse
from app.services.tutor_recommendation import recommend
from scripts.export_tutor_contract import CONTRACT_DIR, SNAPSHOTS, normalize, render

EXAMPLES = Path(CONTRACT_DIR) / "examples"
VALID = sorted((EXAMPLES / "valid").glob("*.json"))
INVALID = sorted((EXAMPLES / "invalid").glob("*.json"))


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", sorted(SNAPSHOTS))
def test_schema_snapshot_has_no_drift(name):
    model, mode = SNAPSHOTS[name]
    committed = json.loads((CONTRACT_DIR / name).read_text(encoding="utf-8"))
    live = json.loads(render(model, mode))
    assert normalize(committed) == normalize(live), (
        "Contract changed: run scripts/export_tutor_contract.py and update "
        "docs/contract.md + notify Backend"
    )


def test_golden_examples_exist():
    assert len(VALID) >= 4
    assert len(INVALID) >= 6


@pytest.mark.parametrize("path", VALID, ids=lambda p: p.stem)
def test_valid_examples_round_trip(path):
    body = load(path)
    model = InternalTutorResponse.model_validate(body)
    assert model.model_dump(mode="json", by_alias=True) == body


@pytest.mark.parametrize("path", INVALID, ids=lambda p: p.stem)
def test_invalid_examples_are_rejected(path):
    with pytest.raises(ValidationError):
        InternalTutorResponse.model_validate(load(path))


def _request(**overrides) -> InternalTutorRequest:
    value = {
        "requestId": str(uuid.uuid4()),
        "conversationId": str(uuid.uuid4()),
        "userId": str(uuid.uuid4()),
        "question": "개념을 다시 설명해줘",
        "modelTier": "BASIC",
        "history": [],
    }
    value.update(overrides)
    return InternalTutorRequest.model_validate(value)


def test_producer_drops_non_uuid_context_ids_instead_of_failing():
    request = _request(
        context={"conceptCode": "ECON_RATE", "stageId": "stage-1", "attemptId": "a-1"}
    )
    meta, action = recommend(request)
    assert meta.schema_version == "1.0"
    assert action.type == "REVIEW_CONCEPT"
    assert action.stage_id is None and action.attempt_id is None


def test_producer_drops_overlong_concept_code():
    request = _request(context={"conceptCode": "C" * 31})
    meta, action = recommend(request)
    assert meta.concept_code is None
    assert action.type == "NONE"


def test_producer_keeps_only_uuid_evidence_question_ids():
    qid = str(uuid.uuid4())
    request = _request(
        context={"conceptCode": "ECON_RATE"},
        personalizedContext={
            "diagnosisEvidence": [
                {"evidenceId": "e1", "evidenceType": "QUESTION_SUBMISSION",
                 "questionId": "not-a-uuid"},
                {"evidenceId": "e2", "evidenceType": "QUESTION_SUBMISSION",
                 "questionId": qid},
                {"evidenceId": "e3", "evidenceType": "QUESTION_SUBMISSION",
                 "questionId": qid.upper()},
            ]
        },
    )
    meta, _ = recommend(request)
    assert meta.diagnosis.evidence_question_ids == [qid]


def test_candidate_input_requires_backend_uuid_ids():
    with pytest.raises(ValidationError):
        _request(
            eligibleQuestionCandidates=[
                {"questionId": "q-1", "conceptCode": "ECON_RATE",
                 "stageId": str(uuid.uuid4()), "attemptId": str(uuid.uuid4())}
            ]
        )


def test_openapi_exposes_source_review_trace_fields():
    from fastapi.testclient import TestClient

    from app.main import app

    schemas = TestClient(app).get("/openapi.json").json()["components"]["schemas"]
    source = schemas["InternalTutorSource"]["properties"]
    assert {"reviewStatus", "licenseReviewStatus"} <= set(source)
    meta = schemas["TutoringMeta"]["properties"]["schemaVersion"]
    assert meta.get("const") == "1.0" or meta.get("enum") == ["1.0"]
