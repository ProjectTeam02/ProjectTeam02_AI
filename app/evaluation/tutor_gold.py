"""Fail-closed validation and review-queue generation for tutor Gold cases.

This module does not promote rows to ``INDEPENDENT_APPROVED``.  It creates
auditable findings and a separate review queue so a human can validate the
concept, evidence, answer draft, and teaching criteria independently.
"""

from __future__ import annotations

import hashlib
import re
from collections import Counter
from typing import Any, Iterable, Mapping

from app.dataset_pipeline.io import NormalizedDocument

FINAL_GOLD_STATUS = "INDEPENDENT_APPROVED"
REVIEW_REQUIRED_STATUS = "REVIEW_REQUIRED"
APPROVED_SOURCE_STATUSES = {"approved", "cleared", "verified"}
REQUIRED_FIELDS = {
    "caseId",
    "sourceIds",
    "conceptCode",
    "difficulty",
    "scenarioType",
    "studentQuestion",
    "learnerProfile",
    "conversationHistory",
    "approvedEvidence",
    "expectedConcepts",
    "expectedMisconception",
    "expectedTeachingBehavior",
    "goldStatus",
}
EVALUATOR_ONLY_FIELDS = {
    "expectedConcepts",
    "expectedMisconception",
    "expectedTeachingBehavior",
    "goldStatus",
    "goldReview",
}
_WHITESPACE = re.compile(r"\s+")


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_question(value: object) -> str:
    return _WHITESPACE.sub(" ", str(value or "").strip()).casefold()


def load_concept_map(payload: Any) -> dict[str, str]:
    """Accept only an explicit mapping; never infer curriculum codes."""

    if isinstance(payload, Mapping):
        if isinstance(payload.get("concepts"), list):
            payload = payload["concepts"]
        else:
            return {
                str(key).strip(): str(value).strip()
                for key, value in payload.items()
                if str(key).strip() and str(value).strip()
            }
    if not isinstance(payload, list):
        return {}
    result: dict[str, str] = {}
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        source_id = str(
            item.get("sourceId") or item.get("documentId") or item.get("id") or ""
        ).strip()
        concept_code = str(item.get("conceptCode") or item.get("code") or "").strip()
        if source_id and concept_code:
            result[source_id] = concept_code
    return result


def validate_tutor_gold(
    rows: Iterable[dict[str, Any]],
    *,
    documents: Iterable[NormalizedDocument] = (),
    concept_map: Mapping[str, str] | None = None,
    require_full_dataset: bool = True,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Validate cases and return a separate human review queue.

    ``require_full_dataset=False`` is reserved for an explicit Interim run.
    It still requires every supplied case to pass the independent Gold gate;
    it only permits the input to be a reviewed subset of the 100-case set.
    """

    rows = list(rows)
    document_by_id = {item.document_id: item for item in documents}
    concept_map = dict(concept_map or {})
    errors: list[dict[str, Any]] = []
    blockers: list[dict[str, Any]] = []
    queue: list[dict[str, Any]] = []
    case_ids = [str(row.get("caseId", "")) for row in rows]
    duplicate_cases = sorted(
        key for key, count in Counter(case_ids).items() if key and count > 1
    )
    duplicate_questions = sorted(
        key
        for key, count in Counter(
            normalize_question(row.get("studentQuestion")) for row in rows
        ).items()
        if key and count > 1
    )
    if require_full_dataset and len(rows) != 100:
        errors.append(
            {"code": "ROW_COUNT", "detail": f"expected 100, found {len(rows)}"}
        )
    for case_id in duplicate_cases:
        errors.append({"code": "DUPLICATE_CASE_ID", "caseId": case_id})
    for question in duplicate_questions:
        errors.append(
            {"code": "DUPLICATE_QUESTION", "questionHash": sha256_text(question)}
        )

    for index, row in enumerate(rows, start=1):
        case_id = str(row.get("caseId", "")).strip() or f"line-{index}"
        row_findings: list[dict[str, Any]] = []
        missing = sorted(REQUIRED_FIELDS - set(row))
        if missing:
            row_findings.append({"code": "REQUIRED_FIELD_MISSING", "fields": missing})
        source_ids = row.get("sourceIds")
        if not isinstance(source_ids, list) or not source_ids:
            row_findings.append({"code": "SOURCE_IDS_INVALID"})
            source_ids = []
        if not str(row.get("studentQuestion", "")).strip():
            row_findings.append({"code": "QUESTION_MISSING"})
        expected = row.get("expectedConcepts")
        if not isinstance(expected, list) or not expected:
            row_findings.append({"code": "ANSWER_CONCEPTS_MISSING"})

        concept_code = str(row.get("conceptCode") or "").strip()
        if not concept_code:
            row_findings.append({"code": "CONCEPT_CODE_MISSING"})
        else:
            mapped_codes = {
                concept_map.get(str(source_id).strip())
                for source_id in source_ids
                if concept_map.get(str(source_id).strip())
            }
            if concept_map and not mapped_codes:
                row_findings.append({"code": "CONCEPT_CODE_NOT_MAPPED"})
            elif mapped_codes and concept_code not in mapped_codes:
                row_findings.append(
                    {
                        "code": "CONCEPT_CODE_MISMATCH",
                        "mappedCodes": sorted(mapped_codes),
                        "value": concept_code,
                    }
                )

        candidates = row.get("evidenceCandidates") or row.get("approvedEvidence", [])
        if not isinstance(candidates, list) or not candidates:
            row_findings.append({"code": "EVIDENCE_CANDIDATE_MISSING"})
            candidates = []
        candidate_by_chunk: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            if not isinstance(candidate, dict):
                row_findings.append({"code": "EVIDENCE_CANDIDATE_INVALID"})
                continue
            source_id = str(
                candidate.get("sourceId") or candidate.get("documentId") or ""
            )
            content = str(candidate.get("content") or "")
            chunk_id = str(candidate.get("chunkId") or "")
            if source_id not in source_ids:
                row_findings.append(
                    {"code": "EVIDENCE_SOURCE_NOT_IN_CASE", "sourceId": source_id}
                )
            if not content:
                row_findings.append(
                    {"code": "EVIDENCE_CONTENT_MISSING", "chunkId": chunk_id}
                )
            expected_hash = str(candidate.get("contentHash") or "")
            if expected_hash and expected_hash != sha256_text(content):
                row_findings.append(
                    {"code": "CONTENT_HASH_MISMATCH", "chunkId": chunk_id}
                )
            document = document_by_id.get(source_id)
            if document is None and document_by_id:
                row_findings.append(
                    {"code": "SOURCE_DOCUMENT_NOT_FOUND", "sourceId": source_id}
                )
            elif document is not None:
                if (
                    document.text_hash != expected_hash
                    and document.text_hash != sha256_text(content)
                ):
                    row_findings.append(
                        {"code": "CANONICAL_CONTENT_MISMATCH", "sourceId": source_id}
                    )
                if (
                    document.source_review_status.casefold()
                    not in APPROVED_SOURCE_STATUSES
                ):
                    row_findings.append(
                        {"code": "SOURCE_REVIEW_REQUIRED", "sourceId": source_id}
                    )
                if document.license_status.casefold() not in APPROVED_SOURCE_STATUSES:
                    row_findings.append(
                        {"code": "LICENSE_REVIEW_REQUIRED", "sourceId": source_id}
                    )
            if chunk_id:
                candidate_by_chunk[chunk_id] = candidate

        approved_evidence = row.get("approvedEvidence", [])
        if not isinstance(approved_evidence, list):
            row_findings.append({"code": "APPROVED_EVIDENCE_INVALID"})
            approved_evidence = []
        for evidence in approved_evidence:
            if not isinstance(evidence, dict):
                row_findings.append({"code": "APPROVED_EVIDENCE_INVALID"})
                continue
            if str(evidence.get("approvalStatus", "")).casefold() != "approved":
                row_findings.append({"code": "EVIDENCE_NOT_APPROVED"})
            if (
                str(evidence.get("licenseStatus", "")).casefold()
                not in APPROVED_SOURCE_STATUSES
            ):
                row_findings.append({"code": "EVIDENCE_LICENSE_NOT_APPROVED"})
            chunk_id = str(evidence.get("chunkId") or "")
            if chunk_id not in candidate_by_chunk:
                row_findings.append(
                    {"code": "APPROVED_EVIDENCE_NOT_IN_CANDIDATES", "chunkId": chunk_id}
                )

        review = row.get("goldReview")
        if row.get("goldStatus") != FINAL_GOLD_STATUS:
            row_findings.append({"code": "INDEPENDENT_REVIEW_REQUIRED"})
        elif not _review_metadata_is_complete(review):
            row_findings.append({"code": "REVIEW_LINEAGE_INCOMPLETE"})
        if (
            row.get("datasetVersion") is None
            and row.get("generation", {}).get("datasetVersion") is None
        ):
            row_findings.append({"code": "DATASET_VERSION_MISSING"})
        if row.get("goldVersion") is None:
            row_findings.append({"code": "GOLD_VERSION_MISSING"})

        public_fields = set(row) & EVALUATOR_ONLY_FIELDS
        if public_fields - {"goldStatus"}:
            # These are valid evaluator fields in the source row; the finding
            # is informational unless they appear in the projected model input.
            pass
        draft = _answer_draft(row, candidates)
        queue.append(
            {
                "caseId": case_id,
                "sourceIds": source_ids,
                "conceptCode": concept_code or None,
                "studentQuestion": row.get("studentQuestion"),
                "answerDraft": draft,
                "expectedConcepts": row.get("expectedConcepts", []),
                "expectedMisconception": row.get("expectedMisconception"),
                "expectedTeachingBehavior": row.get("expectedTeachingBehavior", []),
                "reviewStatus": REVIEW_REQUIRED_STATUS,
                "reviewReasons": row_findings,
            }
        )
        if row_findings:
            blockers.extend({"caseId": case_id, **finding} for finding in row_findings)

    valid_structure = not errors
    ready = valid_structure and bool(rows) and not blockers
    if require_full_dataset:
        ready = ready and len(rows) == 100
    result = {
        "schemaVersion": 1,
        "goldValidatorVersion": "tutor-gold-v1",
        "validStructure": valid_structure,
        "readyForScoring": ready,
        "rowCount": len(rows),
        "fullDatasetRequired": require_full_dataset,
        "expectedRowCount": 100,
        "errorCount": len(errors),
        "blockingFindingCount": len(blockers),
        "errors": errors,
        "blockingFindings": blockers,
        "statusCounts": dict(Counter(str(row.get("goldStatus")) for row in rows)),
        "reviewQueueStatusCounts": dict(
            Counter(str(item["reviewStatus"]) for item in queue)
        ),
        "missingConceptCodeCount": sum(
            not str(row.get("conceptCode") or "").strip() for row in rows
        ),
        "approvedEvidenceRowCount": sum(
            bool(row.get("approvedEvidence")) for row in rows
        ),
        "sourceDocumentChecksEnabled": bool(document_by_id),
        "conceptMappingChecksEnabled": bool(concept_map),
        "independentReviewWasInferred": False,
        "sourceDataModified": False,
    }
    return result, queue


def _review_metadata_is_complete(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    reviewer_id = str(value.get("reviewerId") or "").strip()
    reviewed_at = str(value.get("reviewedAt") or "").strip()
    review_mode = str(value.get("reviewMode") or "").strip()
    reviewer_count = value.get("reviewerCount", 0)
    return bool(
        reviewer_id and reviewed_at and review_mode and int(reviewer_count or 0) >= 2
    )


def _answer_draft(row: dict[str, Any], candidates: list[Any]) -> str | None:
    for candidate in candidates:
        if isinstance(candidate, dict) and str(candidate.get("content") or "").strip():
            content = str(candidate["content"]).strip()
            return f"근거 기반 정답 초안(사람 검수 필요): {content}"
    concepts = [
        str(item).strip()
        for item in row.get("expectedConcepts", [])
        if str(item).strip()
    ]
    return (
        "개념 정답 초안을 작성할 원문 근거가 없습니다. "
        f"검수 대상 개념: {', '.join(concepts)}"
        if concepts
        else None
    )
