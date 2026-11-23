from __future__ import annotations

from app.dataset_pipeline.io import NormalizedDocument, sha256_text
from app.evaluation.tutor_dataset import (
    DIFFICULTY_COUNTS,
    SCENARIO_TYPE_COUNTS,
    build_tutor_dataset,
    public_model_input,
    validate_tutor_dataset,
)


def _documents() -> list[NormalizedDocument]:
    documents = []
    for source in ("KDI", "BOK"):
        for index in range(50):
            content = f"{source} 경제금융 용어 {index}의 원문 정의입니다."
            documents.append(
                NormalizedDocument(
                    source=source,
                    document_id=f"{source}-{index:03d}",
                    title=f"{source} 용어 {index}",
                    content=content,
                    source_url=None,
                    source_locator=f"record={index}",
                    source_name=source,
                    source_version=None,
                    source_review_status="UNKNOWN",
                    license_status="UNCONFIRMED",
                    text_hash=sha256_text(content),
                    related_terms=(),
                    raw_file=f"{source.lower()}_terms.jsonl",
                )
            )
    return documents


def test_builds_exact_distribution_and_balanced_sources() -> None:
    rows = build_tutor_dataset(_documents())
    validation = validate_tutor_dataset(rows, _documents())

    assert validation["valid"]
    assert validation["row_count"] == 100
    assert validation["difficulty_counts"] == DIFFICULTY_COUNTS
    assert validation["scenario_type_counts"] == SCENARIO_TYPE_COUNTS
    assert validation["source_counts"] == {"BOK": 50, "KDI": 50}
    assert validation["gold_status_counts"] == {"PENDING_REVIEW": 100}
    assert validation["approved_evidence_count"] == 0
    assert validation["ready_for_scoring"] is False


def test_multiturn_and_evaluator_fields_are_separated() -> None:
    rows = build_tutor_dataset(_documents())
    multiturn = [row for row in rows if row["scenarioType"] == "D_MULTITURN_CONTEXT"]
    misconception = [
        row for row in rows if row["scenarioType"] == "B_MISCONCEPTION_DIAGNOSIS"
    ]

    assert len(multiturn) == 20
    assert all(len(row["conversationHistory"]) == 10 for row in multiturn)
    assert all(
        row["expectedMisconception"]["status"] == "UNCONFIRMED" for row in misconception
    )
    assert {row["expectedMisconception"]["type"] for row in misconception} == {
        "KNOWLEDGE_GAP",
        "RELATION_ERROR",
        "CAUSAL_ERROR",
        "APPLICATION_ERROR",
        "UNCERTAIN",
    }

    public = public_model_input(rows[0])
    assert "expectedConcepts" not in public
    assert "expectedMisconception" not in public
    assert "expectedTeachingBehavior" not in public
    assert "goldStatus" not in public


def test_unapproved_source_is_candidate_only() -> None:
    rows = build_tutor_dataset(_documents())

    assert all(not row["approvedEvidence"] for row in rows)
    assert all(row["evidenceCandidates"] for row in rows)
    assert all(
        item["approvalStatus"] == "UNKNOWN"
        for row in rows
        for item in row["evidenceCandidates"]
    )
