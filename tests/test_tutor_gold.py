from __future__ import annotations

from app.dataset_pipeline.io import NormalizedDocument, sha256_text
from app.evaluation.tutor_gold import (
    FINAL_GOLD_STATUS,
    REVIEW_REQUIRED_STATUS,
    validate_tutor_gold,
)


def document() -> NormalizedDocument:
    content = "기준금리는 중앙은행의 정책금리입니다."
    return NormalizedDocument(
        source="BOK",
        document_id="bok-1",
        title="기준금리",
        content=content,
        source_url="https://example.test/bok-1",
        source_locator="page=1",
        source_name="BOK",
        source_version="v1",
        source_review_status="approved",
        license_status="verified",
        text_hash=sha256_text(content),
        related_terms=(),
        raw_file="fixture",
    )


def row(*, status: str = "PENDING_REVIEW", code: str | None = None) -> dict:
    content = document().content
    evidence = {
        "sourceId": "bok-1",
        "documentId": "bok-1",
        "chunkId": "BOK:bok-1:chunk-0000",
        "content": content,
        "contentHash": sha256_text(content),
        "source": "BOK",
        "sourceReviewStatus": "approved",
        "licenseStatus": "verified",
        "approvalStatus": "approved",
    }
    value = {
        "caseId": "TUTOR-001",
        "sourceIds": ["bok-1"],
        "conceptCode": code,
        "difficulty": "easy",
        "scenarioType": "A_CONCEPT_EXPLANATION",
        "studentQuestion": "기준금리는 무엇인가요?",
        "learnerProfile": {},
        "conversationHistory": [],
        "approvedEvidence": [evidence],
        "evidenceCandidates": [evidence],
        "expectedConcepts": ["기준금리"],
        "expectedMisconception": None,
        "expectedTeachingBehavior": ["cite_source"],
        "goldStatus": status,
        "datasetVersion": "dataset-v1",
        "goldVersion": "gold-v1",
        "goldReview": {
            "reviewerId": "reviewer-a",
            "reviewedAt": "2026-11-22T00:00:00Z",
            "reviewMode": "ADJUDICATED_CONSENSUS",
            "reviewerCount": 2,
        },
    }
    return value


def test_pending_gold_is_never_promoted_and_is_review_required():
    validation, queue = validate_tutor_gold(
        [row(code=None)], documents=[document()], concept_map={"bok-1": "ECON_RATE"}
    )

    assert validation["readyForScoring"] is False
    assert validation["independentReviewWasInferred"] is False
    assert queue[0]["reviewStatus"] == REVIEW_REQUIRED_STATUS
    assert "INDEPENDENT_REVIEW_REQUIRED" in {
        item["code"] for item in validation["blockingFindings"]
    }


def test_complete_independent_gold_can_pass_when_explicitly_present():
    rows = []
    for index in range(1, 101):
        value = row(status=FINAL_GOLD_STATUS, code="ECON_RATE")
        value["caseId"] = f"TUTOR-{index:03d}"
        value["studentQuestion"] = f"기준금리는 무엇인가요? ({index})"
        rows.append(value)
    validation, queue = validate_tutor_gold(
        rows,
        documents=[document()],
        concept_map={"bok-1": "ECON_RATE"},
    )

    assert validation["readyForScoring"] is True
    assert validation["blockingFindingCount"] == 0
    assert queue[0]["reviewStatus"] == REVIEW_REQUIRED_STATUS


def test_hash_mismatch_and_concept_mapping_mismatch_are_blocked():
    value = row(status=FINAL_GOLD_STATUS, code="ECON_OTHER")
    value["evidenceCandidates"][0]["contentHash"] = "wrong"
    validation, _ = validate_tutor_gold(
        [value], documents=[document()], concept_map={"bok-1": "ECON_RATE"}
    )

    codes = {item["code"] for item in validation["blockingFindings"]}
    assert "CONTENT_HASH_MISMATCH" in codes
    assert "CONCEPT_CODE_MISMATCH" in codes


def test_duplicate_questions_are_reported_without_mutating_rows():
    first = row(code="ECON_RATE")
    second = row(code="ECON_RATE")
    second["caseId"] = "TUTOR-002"
    original_status = first["goldStatus"]

    validation, _ = validate_tutor_gold(
        [first, second], documents=[document()], concept_map={"bok-1": "ECON_RATE"}
    )

    assert validation["validStructure"] is False
    assert any(item["code"] == "ROW_COUNT" for item in validation["errors"])
    assert any(item["code"] == "DUPLICATE_QUESTION" for item in validation["errors"])
    assert first["goldStatus"] == original_status
