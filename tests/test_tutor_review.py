from __future__ import annotations

from app.evaluation.tutor_gold import sha256_text
from app.evaluation.tutor_review import (
    create_adjudication_event,
    create_review_event,
    project_approved_cases,
    validate_history,
    workflow_summary,
)


def _case() -> dict:
    content = "기준금리는 중앙은행이 정하는 정책금리입니다."
    return {
        "caseId": "TUTOR-001",
        "sourceIds": ["DOC-1"],
        "conceptCode": None,
        "datasetVersion": "tutor-test-100-v1",
        "evidenceCandidates": [
            {
                "sourceId": "DOC-1",
                "documentId": "DOC-1",
                "chunkId": "DOC-1:chunk-1",
                "content": content,
                "contentHash": sha256_text(content),
                "approvalStatus": "APPROVED",
                "licenseStatus": "APPROVED",
            }
        ],
        "goldStatus": "PENDING_REVIEW",
    }


def _approval(case: dict, reviewer: str) -> dict:
    return create_review_event(
        case,
        reviewer_id=reviewer,
        status="IN_REVIEW",
        decision="APPROVE",
        concept_code="C0101",
        approved_evidence=case["evidenceCandidates"],
        source_review_status="APPROVED",
        license_status="APPROVED",
        notes="원문과 개념을 독립적으로 확인함",
        canonical_codes={"C0101"},
    )


def test_review_progress_does_not_auto_approve():
    case = _case()

    summary = workflow_summary([case], [])

    assert summary["stage"] == "REVIEW_IN_PROGRESS"
    assert summary["approvedCaseCount"] == 0
    assert summary["autoApproval"] is False


def test_interim_projection_requires_two_reviewers_and_adjudication():
    case = _case()
    first = _approval(case, "reviewer-a")
    second = _approval(case, "reviewer-b")
    assert project_approved_cases([case], [first, second])[1]["status"] == "BLOCKED"

    adjudication = create_adjudication_event(
        case,
        adjudicator_id="adjudicator",
        concept_code="C0101",
        approved_evidence=case["evidenceCandidates"],
        notes="두 독립 검수 결과와 근거를 대조함",
        reviewer_events=[first, second],
        source_review_status="APPROVED",
        license_status="APPROVED",
        canonical_codes={"C0101"},
    )
    projected, status = project_approved_cases(
        [case], [first, second, adjudication], canonical_codes={"C0101"}
    )

    assert status["status"] == "READY"
    assert projected[0]["goldStatus"] == "INDEPENDENT_APPROVED"
    assert projected[0]["goldReview"]["source"] == "human_adjudication_event"


def test_review_history_rejects_noncanonical_concept_and_bad_evidence():
    case = _case()
    event = {
        "eventType": "CASE_REVIEW",
        "caseId": "TUTOR-001",
        "reviewerId": "reviewer-a",
        "decision": "APPROVE",
        "conceptCode": "NOT-CANONICAL",
        "approvedEvidence": [],
    }

    result = validate_history([case], [event], canonical_codes={"C0101"})

    assert result["valid"] is False
    assert result["autoApproval"] is False
    assert result["errors"]
