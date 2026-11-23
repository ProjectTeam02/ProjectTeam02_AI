from __future__ import annotations

import json

import pytest

from app.curation.validation import validate_curation
from app.rag.retrieval.retriever import InMemoryRetriever, Retriever
from app.rag.retrieval.types import RetrievedDocument
from app.schemas.tutor import InternalTutorRequest


def document(document_id: str, *, license_review_status: str | None = None):
    return RetrievedDocument(
        content="기준금리는 중앙은행의 정책금리입니다.",
        source="fixture",
        document_id=document_id,
        chunk_id=f"{document_id}:0",
        title=document_id,
        review_status="approved",
        license="test-only",
        license_review_status=license_review_status,
    )


@pytest.mark.asyncio
async def test_verified_document_scope_and_pending_license_are_enforced():
    results = await Retriever(
        InMemoryRetriever(
            [
                document("approved-doc", license_review_status="approved"),
                document("other-doc", license_review_status="approved"),
                document("pending-doc", license_review_status="PENDING"),
            ]
        )
    ).retrieve("기준금리", document_ids=["approved-doc"])

    assert [item.document_id for item in results] == ["approved-doc"]


def test_verified_context_requires_complete_approved_source_scope():
    payload = {
        "requestId": "00000000-0000-4000-8000-000000000001",
        "conversationId": "00000000-0000-4000-8000-000000000002",
        "userId": "00000000-0000-4000-8000-000000000003",
        "question": "기준금리가 뭐야?",
        "modelTier": "BASIC",
        "verifiedContext": {
            "verificationStatus": "VERIFIED",
            "conceptCode": "ECON_RATE",
            "version": 1,
            "title": "기준금리",
            "sourceDocumentIds": ["doc-1"],
            "sources": [
                {
                    "documentId": "doc-1",
                    "reviewStatus": "approved",
                    "licenseReviewStatus": "approved",
                }
            ],
        },
    }
    request = InternalTutorRequest.model_validate(payload)
    assert request.verified_context.source_document_ids == ["doc-1"]

    blocked = dict(payload)
    blocked["verifiedContext"] = {
        "verificationStatus": "BLOCKED",
        "conceptCode": "ECON_RATE",
        "version": 1,
        "title": "기준금리",
        "blockingReasons": ["CONCEPT_REVIEW_HISTORY_MISSING"],
    }
    blocked_request = InternalTutorRequest.model_validate(blocked)
    assert blocked_request.verified_context.blocking_reasons


def test_curation_validator_reports_missing_inputs_without_substituting_data(tmp_path):
    result = validate_curation(tmp_path)

    assert result["status"] == "BLOCKED"
    assert len(result["missingFiles"]) == 12
    assert result["counts"] == {}
    assert result["approval"]["approvedPrerequisiteRowsAreNotDbApproval"] is True


def test_curation_validator_checks_cycles_and_published_review_history(tmp_path):
    files = {
        "concept/concept_master.json": [{"conceptCode": "A"}],
        "concept/concept_master_1123.json": [
            {"conceptCode": "A", "status": "PUBLISHED"},
            {
                "conceptCode": "B",
                "status": "PUBLISHED",
                "reviewedBy": "u",
                "reviewedAt": "t",
            },
        ],
    }
    for relative, payload in files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    csv_files = {
        "source/bok_documents_raw.csv": "documentId\nD1\n",
        "source/bok_documents.csv": "documentId\nD1\n",
        "source/concept_source_candidates.csv": "conceptCode,documentId\nA,D1\n",
        "source/concept_sources_reviewed.csv": "conceptCode,documentId\nA,D1\n",
        "prerequisite/prerequisite_raw.csv": (
            "conceptCode,prerequisiteConceptCode\nA,B\nB,A\n"
        ),
        "prerequisite/prerequisite_review.csv": (
            "conceptCode,prerequisiteConceptCode,decision\n"
            "A,B,APPROVED\nB,A,APPROVED\n"
        ),
    }
    for relative, content in csv_files.items():
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    for relative in (
        "concept/concept_check.txt",
        "source/source_check.txt",
        "source/source_check_after.txt",
        "db_check/ai_schema_check.txt",
    ):
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PASS\n", encoding="utf-8")

    result = validate_curation(tmp_path)
    assert result["status"] == "BLOCKED"
    assert any("cycles" in error for error in result["errors"])
    assert result["approval"]["publishedConceptsMissingReviewHistory"] == ["A"]
