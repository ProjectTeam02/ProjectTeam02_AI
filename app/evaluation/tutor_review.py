"""Append-only human review workflow for the 100-case tutor Gold set.

The source JSONL is never modified by this module.  Reviewer decisions are
stored as events, and an interim dataset is projected only from an explicit
adjudication supported by independent reviewers and approved evidence.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from app.evaluation.tutor_gold import APPROVED_SOURCE_STATUSES, sha256_text

REVIEW_IN_PROGRESS = "REVIEW_IN_PROGRESS"
INTERIM_MODEL_COMPARISON = "INTERIM_MODEL_COMPARISON"
FINAL_MODEL_EVALUATION = "FINAL_MODEL_EVALUATION"

CASE_STATUSES = {
    "PENDING_REVIEW",
    "IN_REVIEW",
    "REVIEW_REQUIRED",
    "INDEPENDENT_APPROVED",
    "REJECTED",
}
REVIEW_DECISIONS = {"IN_REVIEW", "REVIEW_REQUIRED", "APPROVE", "REJECT"}
APPROVED_REVIEW_STATUSES = {"APPROVE", "INDEPENDENT_APPROVED"}
REVIEW_EVENT = "CASE_REVIEW"
ADJUDICATION_EVENT = "CASE_ADJUDICATION"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must contain an object")
        rows.append(value)
    return rows


def append_event(path: Path, event: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")


def load_canonical_concept_codes(path: Path | None) -> set[str]:
    if path is None or not path.is_file():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    concepts = payload.get("concepts", []) if isinstance(payload, Mapping) else payload
    if not isinstance(concepts, list):
        return set()
    return {
        str(item.get("conceptCode") or item.get("code") or "").strip()
        for item in concepts
        if isinstance(item, Mapping)
        and str(item.get("conceptCode") or item.get("code") or "").strip()
    }


def _case_by_id(rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(row.get("caseId", "")).strip(): row for row in rows}


def _evidence_by_chunk(case: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    candidates = case.get("evidenceCandidates", [])
    return {
        str(item.get("chunkId") or "").strip(): item
        for item in candidates
        if isinstance(item, Mapping) and str(item.get("chunkId") or "").strip()
    }


def _validate_evidence(
    case: Mapping[str, Any],
    evidence: Any,
    *,
    require_approved: bool,
    canonical_codes: set[str],
) -> list[str]:
    errors: list[str] = []
    if not isinstance(evidence, list) or not evidence:
        return ["approvedEvidence must be a non-empty list"]
    candidates = _evidence_by_chunk(case)
    source_ids = {str(item).strip() for item in case.get("sourceIds", [])}
    for item in evidence:
        if not isinstance(item, Mapping):
            errors.append("approvedEvidence item must be an object")
            continue
        source_id = str(item.get("sourceId") or item.get("documentId") or "").strip()
        chunk_id = str(item.get("chunkId") or "").strip()
        content = str(item.get("content") or "")
        if source_id not in source_ids:
            errors.append(f"evidence source is not listed in case: {source_id}")
        if chunk_id not in candidates:
            errors.append(f"evidence chunk is not a candidate: {chunk_id}")
        candidate = candidates.get(chunk_id)
        if candidate is not None:
            candidate_hash = str(candidate.get("contentHash") or "").strip()
            if candidate_hash and candidate_hash != str(item.get("contentHash") or ""):
                errors.append(f"evidence content hash mismatch: {chunk_id}")
            if str(candidate.get("content") or "") != content:
                errors.append(f"evidence content mismatch: {chunk_id}")
        if content and str(item.get("contentHash") or "") != sha256_text(content):
            errors.append(f"evidence hash does not match content: {chunk_id}")
        if require_approved:
            if str(item.get("approvalStatus", "")).casefold() != "approved":
                errors.append(f"evidence is not source-approved: {chunk_id}")
            if (
                str(item.get("licenseStatus", "")).casefold()
                not in APPROVED_SOURCE_STATUSES
            ):
                errors.append(f"evidence license is not approved: {chunk_id}")
    if canonical_codes and not str(case.get("conceptCode") or "").strip():
        errors.append("canonical conceptCode is required")
    return errors


def create_review_event(
    case: Mapping[str, Any],
    *,
    reviewer_id: str,
    status: str,
    decision: str,
    notes: str,
    concept_code: str | None = None,
    approved_evidence: list[dict[str, Any]] | None = None,
    source_review_status: str = "PENDING",
    license_status: str = "PENDING",
    canonical_codes: set[str] | None = None,
) -> dict[str, Any]:
    """Create one reviewer event without changing the Gold source row."""

    case_id = str(case.get("caseId", "")).strip()
    reviewer_id = reviewer_id.strip()
    decision = decision.upper().strip()
    status = status.upper().strip()
    concept_code = (concept_code or "").strip() or None
    if not case_id or not reviewer_id or not notes.strip():
        raise ValueError("caseId, reviewer_id, and notes are required")
    if status not in CASE_STATUSES or decision not in REVIEW_DECISIONS:
        raise ValueError("invalid review status or decision")
    if decision == "APPROVE":
        if status not in {"IN_REVIEW", "INDEPENDENT_APPROVED"}:
            raise ValueError("APPROVE requires IN_REVIEW or INDEPENDENT_APPROVED")
        if not concept_code:
            raise ValueError("conceptCode is required for approval")
        if canonical_codes and concept_code not in canonical_codes:
            raise ValueError("conceptCode is not in the canonical concept master")
        if source_review_status.casefold() not in APPROVED_SOURCE_STATUSES:
            raise ValueError("source review must be approved before case approval")
        if license_status.casefold() not in APPROVED_SOURCE_STATUSES:
            raise ValueError("license review must be approved before case approval")
        evidence_errors = _validate_evidence(
            {**case, "conceptCode": concept_code},
            approved_evidence,
            require_approved=True,
            canonical_codes=canonical_codes or set(),
        )
        if evidence_errors:
            raise ValueError("; ".join(evidence_errors))
    event_id = hashlib.sha256(
        f"review|{case_id}|{reviewer_id}|{utc_now()}".encode()
    ).hexdigest()[:20]
    return {
        "schemaVersion": 1,
        "eventId": event_id,
        "eventType": REVIEW_EVENT,
        "caseId": case_id,
        "reviewerId": reviewer_id,
        "reviewedAt": utc_now(),
        "status": status,
        "decision": decision,
        "conceptCode": concept_code,
        "approvedEvidence": approved_evidence or [],
        "sourceReviewStatus": source_review_status.upper(),
        "licenseStatus": license_status.upper(),
        "notes": notes.strip(),
        "datasetVersion": case.get("datasetVersion")
        or case.get("generation", {}).get("datasetVersion"),
    }


def create_adjudication_event(
    case: Mapping[str, Any],
    *,
    adjudicator_id: str,
    concept_code: str,
    approved_evidence: list[dict[str, Any]],
    notes: str,
    reviewer_events: Iterable[dict[str, Any]],
    source_review_status: str,
    license_status: str,
    canonical_codes: set[str] | None = None,
) -> dict[str, Any]:
    reviewers = {
        str(event.get("reviewerId", "")).strip()
        for event in reviewer_events
        if event.get("eventType") == REVIEW_EVENT
        and event.get("decision") == "APPROVE"
        and str(event.get("reviewerId", "")).strip()
    }
    if len(reviewers) < 2:
        raise ValueError("adjudication requires two independent approving reviewers")
    if adjudicator_id.strip() in reviewers:
        raise ValueError("adjudicator must be independent from the reviewers")
    projected = dict(case)
    projected["conceptCode"] = concept_code
    evidence_errors = _validate_evidence(
        projected,
        approved_evidence,
        require_approved=True,
        canonical_codes=canonical_codes or set(),
    )
    if canonical_codes and concept_code not in canonical_codes:
        evidence_errors.append("conceptCode is not in the canonical concept master")
    if source_review_status.casefold() not in APPROVED_SOURCE_STATUSES:
        evidence_errors.append("source review must be approved")
    if license_status.casefold() not in APPROVED_SOURCE_STATUSES:
        evidence_errors.append("license must be approved")
    if not adjudicator_id.strip() or not notes.strip():
        evidence_errors.append("adjudicator_id and notes are required")
    if evidence_errors:
        raise ValueError("; ".join(evidence_errors))
    return {
        "schemaVersion": 1,
        "eventId": hashlib.sha256(
            f"adjudication|{case.get('caseId')}|{adjudicator_id}|{utc_now()}".encode()
        ).hexdigest()[:20],
        "eventType": ADJUDICATION_EVENT,
        "caseId": case.get("caseId"),
        "reviewerId": adjudicator_id.strip(),
        "reviewedAt": utc_now(),
        "status": "INDEPENDENT_APPROVED",
        "decision": "APPROVE",
        "reviewerIds": sorted(reviewers),
        "reviewerCount": len(reviewers),
        "reviewMode": "ADJUDICATED_CONSENSUS",
        "conceptCode": concept_code,
        "approvedEvidence": approved_evidence,
        "sourceReviewStatus": source_review_status.upper(),
        "licenseStatus": license_status.upper(),
        "notes": notes.strip(),
        "datasetVersion": case.get("datasetVersion")
        or case.get("generation", {}).get("datasetVersion"),
    }


def _latest_review_events(
    events: Iterable[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        if event.get("eventType") != REVIEW_EVENT:
            continue
        key = (str(event.get("caseId", "")), str(event.get("reviewerId", "")))
        if all(key):
            latest[key] = event
    return latest


def _adjudications(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("eventType") == ADJUDICATION_EVENT:
            case_id = str(event.get("caseId", ""))
            if case_id:
                latest[case_id] = event
    return latest


def validate_history(
    rows: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    *,
    canonical_codes: set[str] | None = None,
) -> dict[str, Any]:
    cases = _case_by_id(rows)
    history = list(events)
    errors: list[dict[str, Any]] = []
    for event in history:
        case_id = str(event.get("caseId", ""))
        case = cases.get(case_id)
        if case is None:
            errors.append({"code": "UNKNOWN_CASE", "caseId": case_id})
            continue
        if event.get("eventType") not in {REVIEW_EVENT, ADJUDICATION_EVENT}:
            errors.append({"code": "UNKNOWN_EVENT_TYPE", "caseId": case_id})
        if not str(event.get("reviewerId", "")).strip():
            errors.append({"code": "REVIEWER_MISSING", "caseId": case_id})
        if event.get("decision") == "APPROVE":
            if event.get("eventType") == REVIEW_EVENT:
                if not event.get("conceptCode"):
                    errors.append({"code": "CONCEPT_CODE_MISSING", "caseId": case_id})
                if canonical_codes and event.get("conceptCode") not in canonical_codes:
                    errors.append(
                        {"code": "CONCEPT_CODE_NOT_CANONICAL", "caseId": case_id}
                    )
                errors.extend(
                    {"code": "EVIDENCE_INVALID", "caseId": case_id, "detail": detail}
                    for detail in _validate_evidence(
                        {**case, "conceptCode": event.get("conceptCode")},
                        event.get("approvedEvidence"),
                        require_approved=True,
                        canonical_codes=canonical_codes or set(),
                    )
                )
            elif event.get("eventType") == ADJUDICATION_EVENT:
                reviewer_ids = {
                    str(value).strip()
                    for value in event.get("reviewerIds", [])
                    if str(value).strip()
                }
                if len(reviewer_ids) < 2:
                    errors.append(
                        {"code": "INDEPENDENT_REVIEWERS_MISSING", "caseId": case_id}
                    )
                if str(event.get("reviewerId", "")).strip() in reviewer_ids:
                    errors.append(
                        {"code": "ADJUDICATOR_NOT_INDEPENDENT", "caseId": case_id}
                    )
                errors.extend(
                    {"code": "EVIDENCE_INVALID", "caseId": case_id, "detail": detail}
                    for detail in _validate_evidence(
                        {**case, "conceptCode": event.get("conceptCode")},
                        event.get("approvedEvidence"),
                        require_approved=True,
                        canonical_codes=canonical_codes or set(),
                    )
                )
    latest = _latest_review_events(history)
    adjudications = _adjudications(history)
    status_counts = Counter(
        case_status(case, latest, adjudications)
        for case in cases.values()
    )
    return {
        "valid": not errors,
        "errors": errors,
        "caseCount": len(cases),
        "eventCount": len(history),
        "statusCounts": dict(status_counts),
        "adjudicatedCount": sum(
            event.get("status") == "INDEPENDENT_APPROVED"
            for event in adjudications.values()
        ),
        "autoApproval": False,
    }


def case_status(
    case: Mapping[str, Any],
    latest_reviews: Mapping[tuple[str, str], dict[str, Any]],
    adjudications: Mapping[str, dict[str, Any]],
) -> str:
    case_id = str(case.get("caseId", ""))
    adjudication = adjudications.get(case_id)
    if adjudication and adjudication.get("status") == "INDEPENDENT_APPROVED":
        return "INDEPENDENT_APPROVED"
    reviews = [event for (key, _), event in latest_reviews.items() if key == case_id]
    decisions = {str(event.get("decision", "")) for event in reviews}
    if "REJECT" in decisions:
        return "REJECTED"
    review_concepts = {
        event.get("conceptCode") for event in reviews if event.get("conceptCode")
    }
    if len(review_concepts) > 1:
        return "REVIEW_REQUIRED"
    if "REVIEW_REQUIRED" in decisions:
        return "REVIEW_REQUIRED"
    if reviews:
        return "IN_REVIEW"
    return str(case.get("goldStatus") or "PENDING_REVIEW")


def workflow_stage(case_count: int, approved_count: int, event_count: int) -> str:
    if approved_count == case_count and case_count > 0:
        return FINAL_MODEL_EVALUATION
    if approved_count > 0:
        return INTERIM_MODEL_COMPARISON
    return REVIEW_IN_PROGRESS if event_count or case_count else REVIEW_IN_PROGRESS


def review_queue(
    rows: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    *,
    canonical_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    history = list(events)
    latest = _latest_review_events(history)
    adjudications = _adjudications(history)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (case_id, _), event in latest.items():
        grouped[case_id].append(event)
    queue: list[dict[str, Any]] = []
    for case in rows:
        case_id = str(case.get("caseId", ""))
        queue.append(
            {
                "caseId": case_id,
                "studentQuestion": case.get("studentQuestion"),
                "sourceIds": case.get("sourceIds", []),
                "conceptCode": case.get("conceptCode"),
                "conceptCodeCanonical": bool(
                    case.get("conceptCode") and (
                        not canonical_codes
                        or case.get("conceptCode") in canonical_codes
                    )
                ),
                "evidenceCandidates": case.get("evidenceCandidates", []),
                "expectedMisconception": case.get("expectedMisconception"),
                "expectedTeachingBehavior": case.get("expectedTeachingBehavior", []),
                "goldStatus": case.get("goldStatus"),
                "workflowStatus": case_status(case, latest, adjudications),
                "reviewerCount": len(grouped.get(case_id, [])),
                "reviewRequired": case_status(case, latest, adjudications)
                in {"PENDING_REVIEW", "REVIEW_REQUIRED"},
                "approvalPolicy": (
                    "two independent reviewers + adjudication + "
                    "source/license approval"
                ),
            }
        )
    return queue


def project_approved_cases(
    rows: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    *,
    canonical_codes: set[str] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = _case_by_id(rows)
    event_list = list(events)
    adjudications = _adjudications(event_list)
    projected: list[dict[str, Any]] = []
    blocked: list[dict[str, Any]] = []
    for case_id, event in adjudications.items():
        case = cases.get(case_id)
        if case is None or event.get("status") != "INDEPENDENT_APPROVED":
            continue
        reviewer_ids = {
            str(value).strip()
            for value in event.get("reviewerIds", [])
            if str(value).strip()
        }
        approving_reviewers = {
            str(review.get("reviewerId", "")).strip()
            for review in event_list
            if review.get("eventType") == REVIEW_EVENT
            and str(review.get("caseId", "")) == case_id
            and review.get("decision") == "APPROVE"
            and str(review.get("reviewerId", "")).strip()
        }
        if (
            len(reviewer_ids) < 2
            or not reviewer_ids.issubset(approving_reviewers)
            or str(event.get("reviewerId", "")).strip() in reviewer_ids
        ):
            blocked.append(
                {
                    "caseId": case_id,
                    "reason": "INDEPENDENT_REVIEW_EVIDENCE_MISSING",
                }
            )
            continue
        candidate = dict(case)
        candidate["conceptCode"] = event.get("conceptCode")
        candidate["approvedEvidence"] = event.get("approvedEvidence", [])
        candidate["goldStatus"] = "INDEPENDENT_APPROVED"
        candidate["goldVersion"] = "tutor-gold-review-v1"
        candidate["goldReview"] = {
            "reviewerId": event.get("reviewerId"),
            "reviewerIds": event.get("reviewerIds", []),
            "reviewedAt": event.get("reviewedAt"),
            "reviewMode": event.get("reviewMode"),
            "reviewerCount": event.get("reviewerCount"),
            "source": "human_adjudication_event",
        }
        candidate["datasetVersion"] = (
            event.get("datasetVersion") or case.get("datasetVersion")
        )
        if not candidate["datasetVersion"]:
            blocked.append({"caseId": case_id, "reason": "DATASET_VERSION_MISSING"})
            continue
        errors = _validate_evidence(
            candidate,
            candidate["approvedEvidence"],
            require_approved=True,
            canonical_codes=canonical_codes or set(),
        )
        if canonical_codes and candidate["conceptCode"] not in canonical_codes:
            errors.append("CONCEPT_CODE_NOT_CANONICAL")
        if errors:
            blocked.append({"caseId": case_id, "reason": errors})
            continue
        projected.append(candidate)
    return projected, {
        "status": "READY" if projected else "BLOCKED",
        "approvedCount": len(projected),
        "blockedCount": len(blocked),
        "blocked": blocked,
        "sourceRowsUnmodified": True,
        "approvalWasInferred": False,
    }


def workflow_summary(
    rows: Iterable[dict[str, Any]],
    events: Iterable[dict[str, Any]],
    *,
    canonical_codes: set[str] | None = None,
) -> dict[str, Any]:
    row_list = list(rows)
    event_list = list(events)
    validation = validate_history(row_list, event_list, canonical_codes=canonical_codes)
    approved, projection = project_approved_cases(
        row_list, event_list, canonical_codes=canonical_codes
    )
    return {
        **validation,
        "stage": workflow_stage(
            len(row_list), len(approved), len(event_list)
        ),
        "approvedCaseCount": len(approved),
        "interimProjection": projection,
    }
