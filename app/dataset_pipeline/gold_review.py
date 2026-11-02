"""Local human review state management for the independent Gold Set.

이 모듈은 검수 UI와 검증 스크립트가 같은 저장 규칙을 사용하도록 합니다.
원문 템플릿은 읽기 전용으로 취급하고, 사람의 판정은 append-only JSONL
history에 기록합니다. 같은 평가자의 수정은 새 이벤트로 남고, 다른
평가자의 결과나 adjudication 결과를 덮어쓰지 않습니다.
"""

from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

REVIEW_LABELS = {"0", "1", "2", "NEEDS_REVIEW"}
REVIEW_STATUSES = {"SINGLE_REVIEWED", "ADJUDICATED"}
ADJUDICATION_STATUSES = {"NOT_STARTED", "PENDING", "ADJUDICATED"}
REVIEW_MODES = {"ADJUDICATED_CONSENSUS", "THIRD_PARTY_REVIEW"}
QUALITY_REVIEW_STATUSES = {"PENDING", "APPROVED", "REJECTED", "NEEDS_REVIEW"}
EXPORT_FIELDS = [
    "document_id",
    "chunk_id",
    "source",
    "title",
    "content_hash",
    "chapter_id",
    "dataset_version",
    "rubric_version",
    "sampling_bucket",
    "split",
    "reviewer_id",
    "relevance_label",
    "evidence_quote",
    "reason",
    "review_status",
    "reviewed_at",
    "final_gold_label",
    "adjudication_status",
    "reviewer_count",
    "review_mode",
    "source_review_status",
    "license_review_status",
    "quiz_suitability",
]


def text(value: object) -> str:
    """Normalize empty spreadsheet/CSV values without inventing data."""
    normalized = "" if value is None else str(value).strip()
    return "" if normalized.casefold() in {"", "nan", "none", "null"} else normalized


def normalized_text(value: str) -> str:
    """Normalize whitespace for evidence matching while preserving original text."""
    return " ".join(text(value).split()).casefold()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_template_rows(paths: Iterable[Path]) -> list[dict[str, str]]:
    """Load reviewer rows and reject duplicate document IDs across templates."""
    rows: list[dict[str, str]] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"검수 템플릿이 없습니다: {path}")
        with path.open(encoding="utf-8-sig", newline="") as handle:
            for row in csv.DictReader(handle):
                normalized = {key: text(value) for key, value in row.items()}
                normalized["template_path"] = str(path)
                rows.append(normalized)
    return rows


def load_history(path: Path) -> list[dict[str, Any]]:
    """Read append-only review events; an absent file means no reviews yet."""
    if not path.is_file():
        return []
    events: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(
                f"{path}:{line_number} 검수 이력은 JSON object여야 합니다."
            )
        events.append(value)
    return events


def latest_reviewer_events(
    events: Iterable[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return the latest event per document and reviewer without losing history."""
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for event in events:
        if text(event.get("review_status")) != "SINGLE_REVIEWED":
            continue
        key = (text(event.get("document_id")), text(event.get("reviewer_id")))
        if all(key):
            latest[key] = event
    return latest


def latest_adjudications(events: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return adjudication events keyed by document without allowing overwrite."""
    latest: dict[str, dict[str, Any]] = {}
    for event in events:
        if text(event.get("adjudication_status")) != "ADJUDICATED":
            continue
        document_id = text(event.get("document_id"))
        if document_id and document_id not in latest:
            latest[document_id] = event
    return latest


def evidence_matches(content: str, evidence_quote: str) -> bool:
    """Check that a reviewer quote is present after harmless whitespace folding."""
    quote = normalized_text(evidence_quote)
    return bool(quote) and quote in normalized_text(content)


def validate_decision(
    template: dict[str, str],
    reviewer_id: str,
    relevance_label: str,
    evidence_quote: str,
    reason: str,
    source_review_status: str = "PENDING",
    license_review_status: str = "PENDING",
    quiz_suitability: str = "PENDING",
) -> list[str]:
    """Validate one human decision before it enters the history file."""
    errors: list[str] = []
    if not text(reviewer_id):
        errors.append("reviewer_id_missing")
    if relevance_label not in REVIEW_LABELS:
        errors.append("relevance_label_must_be_0_1_2_or_NEEDS_REVIEW")
    if not text(reason):
        errors.append("reason_missing")
    if relevance_label != "NEEDS_REVIEW" and not evidence_matches(
        template.get("content", ""), evidence_quote
    ):
        errors.append("evidence_quote_not_found_in_original_content")
    if not text(template.get("document_id")):
        errors.append("document_id_missing")
    if not text(template.get("content_hash")):
        errors.append("content_hash_missing")
    if not text(template.get("dataset_version")):
        errors.append("dataset_version_missing")
    if text(template.get("chapter_id")) != "inflation":
        errors.append("unexpected_chapter_id")
    for field, value in (
        ("source_review_status", source_review_status),
        ("license_review_status", license_review_status),
        ("quiz_suitability", quiz_suitability),
    ):
        if value not in QUALITY_REVIEW_STATUSES:
            errors.append(f"{field}_invalid")
    return errors


def append_event(path: Path, event: dict[str, Any]) -> None:
    """Append one immutable event and keep the local directory private."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, ensure_ascii=False) + "\n")


def create_review_event(
    template: dict[str, str],
    reviewer_id: str,
    relevance_label: str,
    evidence_quote: str,
    reason: str,
    rubric_version: str,
    source_review_status: str = "PENDING",
    license_review_status: str = "PENDING",
    quiz_suitability: str = "PENDING",
) -> dict[str, Any]:
    """Create a single-review event; it is never presented as final Gold."""
    errors = validate_decision(
        template,
        reviewer_id,
        relevance_label,
        evidence_quote,
        reason,
        source_review_status,
        license_review_status,
        quiz_suitability,
    )
    if errors:
        raise ValueError("검수 결과를 저장할 수 없습니다: " + ", ".join(errors))
    return {
        "event_id": hashlib.sha256(
            f"{template['document_id']}|{reviewer_id}|{utc_now()}".encode()
        ).hexdigest()[:16],
        "document_id": template["document_id"],
        "chunk_id": template.get("chunk_id", ""),
        "source": template.get("source", ""),
        "title": template.get("title", ""),
        "content_hash": template.get("content_hash", ""),
        "chapter_id": template.get("chapter_id", "inflation"),
        "dataset_version": template.get("dataset_version", ""),
        "rubric_version": rubric_version or template.get("rubric_version", ""),
        "sampling_bucket": template.get("sampling_bucket", ""),
        "split": template.get("split", ""),
        "reviewer_id": text(reviewer_id),
        "relevance_label": relevance_label,
        "evidence_quote": text(evidence_quote),
        "reason": text(reason),
        "review_status": "SINGLE_REVIEWED",
        "reviewed_at": utc_now(),
        "final_gold_label": "",
        "adjudication_status": "PENDING",
        "reviewer_count": "1",
        "review_mode": "",
        "source_review_status": source_review_status,
        "license_review_status": license_review_status,
        "quiz_suitability": quiz_suitability,
    }


def create_adjudication_event(
    template: dict[str, str],
    adjudicator_id: str,
    final_gold_label: str,
    evidence_quote: str,
    reason: str,
    reviewer_count: int,
    review_mode: str,
    prior_events: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Create one final adjudication only when prior independent reviews exist."""
    if final_gold_label not in {"0", "1", "2"}:
        raise ValueError("final_gold_label은 0, 1, 2 중 하나여야 합니다.")
    if not text(adjudicator_id) or not text(reason) or not text(evidence_quote):
        raise ValueError("adjudicator_id, 근거 문장, 합의 근거는 필수입니다.")
    if not evidence_matches(template.get("content", ""), evidence_quote):
        raise ValueError("합의 근거 문장이 원문에서 확인되지 않습니다.")
    if review_mode not in REVIEW_MODES:
        raise ValueError("지원하지 않는 review_mode입니다.")
    reviewer_ids = {
        text(event.get("reviewer_id"))
        for event in prior_events
        if text(event.get("document_id")) == template.get("document_id")
        and text(event.get("reviewer_id"))
        and text(event.get("review_status")) == "SINGLE_REVIEWED"
    }
    minimum = 2 if review_mode == "ADJUDICATED_CONSENSUS" else 1
    if len(reviewer_ids) < minimum:
        raise ValueError(
            f"독립 검수자가 {minimum}명 이상 필요합니다. "
            f"현재 {len(reviewer_ids)}명입니다."
        )
    actual_reviewer_count = len(reviewer_ids)
    if reviewer_count != actual_reviewer_count:
        raise ValueError("reviewer_count가 실제 독립 검수자 수와 다릅니다.")
    return {
        "event_id": hashlib.sha256(
            f"adjudication|{template['document_id']}|{adjudicator_id}|{utc_now()}".encode()
        ).hexdigest()[:16],
        "document_id": template["document_id"],
        "chunk_id": template.get("chunk_id", ""),
        "source": template.get("source", ""),
        "title": template.get("title", ""),
        "content_hash": template.get("content_hash", ""),
        "chapter_id": template.get("chapter_id", "inflation"),
        "dataset_version": template.get("dataset_version", ""),
        "rubric_version": template.get("rubric_version", ""),
        "sampling_bucket": template.get("sampling_bucket", ""),
        "split": template.get("split", ""),
        "reviewer_id": text(adjudicator_id),
        "relevance_label": "",
        "evidence_quote": text(evidence_quote),
        "reason": text(reason),
        "review_status": "ADJUDICATED",
        "reviewed_at": utc_now(),
        "final_gold_label": final_gold_label,
        "adjudication_status": "ADJUDICATED",
        "reviewer_count": str(actual_reviewer_count),
        "review_mode": review_mode,
        "source_review_status": "PENDING",
        "license_review_status": "PENDING",
        "quiz_suitability": "PENDING",
    }


def progress_summary(
    templates: Iterable[dict[str, str]], events: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Summarize completion without treating single reviews as final Gold."""
    template_rows = list(templates)
    latest = latest_reviewer_events(events)
    adjudications = latest_adjudications(events)
    template_ids = {text(row.get("document_id")) for row in template_rows}
    reviewed_ids = {
        document_id for document_id, _ in latest if document_id in template_ids
    }
    by_source = Counter(row.get("source", "") for row in template_rows)
    reviewed_by_source = Counter(
        row.get("source", "")
        for row in template_rows
        if row.get("document_id") in reviewed_ids
    )
    label_counts = Counter(
        text(event.get("relevance_label"))
        for event in latest.values()
        if text(event.get("relevance_label"))
    )
    return {
        "template_count": len(template_rows),
        "reviewed_document_count": len(reviewed_ids),
        "pending_document_count": len(template_ids - reviewed_ids),
        "adjudicated_document_count": len(set(adjudications) & template_ids),
        "source_counts": dict(by_source),
        "reviewed_source_counts": dict(reviewed_by_source),
        "label_counts": dict(label_counts),
        "final_gold_ready": len(set(adjudications) & template_ids),
        "final_gold_is_not_inferred": True,
    }


def disagreement_report(
    templates: Iterable[dict[str, str]], events: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Identify documents whose latest independent reviewers disagree."""
    template_by_id = {
        text(row.get("document_id")): row
        for row in templates
        if text(row.get("document_id"))
    }
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (document_id, _), event in latest_reviewer_events(events).items():
        if document_id in template_by_id:
            grouped[document_id].append(event)
    items: list[dict[str, Any]] = []
    for document_id, reviewer_events in sorted(grouped.items()):
        labels = {text(event.get("relevance_label")) for event in reviewer_events}
        if len(reviewer_events) < 2 or len(labels) <= 1:
            continue
        items.append(
            {
                "document_id": document_id,
                "source": template_by_id[document_id].get("source", ""),
                "title": template_by_id[document_id].get("title", ""),
                "reviewers": [
                    {
                        "reviewer_id": text(event.get("reviewer_id")),
                        "relevance_label": text(event.get("relevance_label")),
                        "reviewed_at": text(event.get("reviewed_at")),
                    }
                    for event in sorted(
                        reviewer_events,
                        key=lambda item: text(item.get("reviewer_id")),
                    )
                ],
                "labels": sorted(labels),
                "adjudication_required": True,
            }
        )
    return {
        "disagreement_count": len(items),
        "items": items,
        "gold_is_not_auto_approved": True,
    }


def export_current_reviews(
    templates: Iterable[dict[str, str]],
    events: Iterable[dict[str, Any]],
    csv_path: Path,
    jsonl_path: Path,
) -> dict[str, Any]:
    """Export latest reviewer events and adjudications for human inspection."""
    template_by_id = {row.get("document_id"): row for row in templates}
    latest = latest_reviewer_events(events)
    adjudications = latest_adjudications(events)
    rows: list[dict[str, Any]] = []
    for (document_id, _), event in sorted(latest.items()):
        if document_id not in template_by_id:
            continue
        rows.append({field: event.get(field, "") for field in EXPORT_FIELDS})
    for document_id, event in sorted(adjudications.items()):
        if document_id not in template_by_id:
            continue
        rows.append({field: event.get(field, "") for field in EXPORT_FIELDS})
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=EXPORT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    jsonl_path.parent.mkdir(parents=True, exist_ok=True)
    jsonl_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    return {"row_count": len(rows), "csv": str(csv_path), "jsonl": str(jsonl_path)}


def build_gold_template_rows(
    templates: Iterable[dict[str, str]], events: Iterable[dict[str, Any]]
) -> list[dict[str, str]]:
    """Project adjudicated events onto the existing assembler template contract.

    사람이 합의한 행만 ``APPROVED``/``INDEPENDENT_APPROVED``로 변환합니다.
    아직 합의되지 않은 행은 원래 템플릿의 빈 상태를 그대로 유지합니다.
    """
    template_rows = [dict(row) for row in templates]
    latest_reviewers = latest_reviewer_events(events)
    adjudications = latest_adjudications(events)
    for row in template_rows:
        event = adjudications.get(text(row.get("document_id")))
        if event is None:
            row["final_gold"] = ""
            row["review_status"] = "PENDING"
            row["gold_set_status"] = "PENDING_INDEPENDENT_REVIEW"
            continue
        reviewer_events = [
            reviewer_event
            for (document_id, _), reviewer_event in latest_reviewers.items()
            if document_id == text(row.get("document_id"))
        ]
        quality_statuses = {
            field: next(
                (
                    text(reviewer_event.get(field))
                    for reviewer_event in reviewer_events
                    if text(reviewer_event.get(field))
                ),
                "PENDING",
            )
            for field in (
                "source_review_status",
                "license_review_status",
                "quiz_suitability",
            )
        }
        row.update(
            {
                "final_gold": text(event.get("final_gold_label")),
                "evidence_quote": text(event.get("evidence_quote")),
                "reason": text(event.get("reason")),
                "review_status": "APPROVED",
                "reviewer_count": text(event.get("reviewer_count")),
                "review_mode": text(event.get("review_mode")),
                "reviewed_at": text(event.get("reviewed_at")),
                "gold_set_status": "INDEPENDENT_APPROVED",
                **quality_statuses,
            }
        )
    return template_rows


def validate_history(
    templates: Iterable[dict[str, str]], events: Iterable[dict[str, Any]]
) -> dict[str, Any]:
    """Validate persisted reviews, including leakage and evidence checks."""
    template_rows = list(templates)
    history = list(events)
    by_id = {row.get("document_id"): row for row in template_rows}
    errors: list[dict[str, Any]] = []
    duplicate_ids = [
        document_id
        for document_id, count in Counter(
            row.get("document_id") for row in template_rows
        ).items()
        if document_id and count > 1
    ]
    for document_id in duplicate_ids:
        errors.append({"type": "duplicate_document_id", "document_id": document_id})
    hashes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for row in template_rows:
        for field in ("source", "title", "content", "content_hash", "document_id"):
            if not text(row.get(field)):
                errors.append(
                    {
                        "type": "template_required_field_missing",
                        "document_id": row.get("document_id", ""),
                        "field": field,
                    }
                )
        hashes[(row.get("source", ""), row.get("content_hash", ""))].append(
            row.get("document_id", "")
        )
    for (source, content_hash), document_ids in hashes.items():
        if content_hash and len(document_ids) > 1:
            errors.append(
                {
                    "type": "duplicate_content_hash_within_source",
                    "source": source,
                    "content_hash": content_hash,
                    "document_ids": document_ids,
                }
            )
    for event in history:
        document_id = text(event.get("document_id"))
        template = by_id.get(document_id)
        if template is None:
            errors.append({"type": "unknown_document_id", "document_id": document_id})
            continue
        if not text(event.get("reviewer_id")):
            errors.append({"type": "reviewer_missing", "document_id": document_id})
        if text(event.get("content_hash")) != text(template.get("content_hash")):
            errors.append({"type": "content_hash_mismatch", "document_id": document_id})
        label = text(event.get("relevance_label"))
        final_label = text(event.get("final_gold_label"))
        if label and label not in REVIEW_LABELS:
            errors.append(
                {"type": "invalid_relevance_label", "document_id": document_id}
            )
        if final_label and final_label not in {"0", "1", "2"}:
            errors.append(
                {"type": "invalid_final_gold_label", "document_id": document_id}
            )
        if (
            label
            and label != "NEEDS_REVIEW"
            and not evidence_matches(
                template.get("content", ""), text(event.get("evidence_quote"))
            )
        ):
            errors.append(
                {"type": "evidence_not_in_original", "document_id": document_id}
            )
        if text(event.get("dataset_version")) != text(template.get("dataset_version")):
            errors.append(
                {"type": "dataset_version_mismatch", "document_id": document_id}
            )
        if final_label and text(event.get("adjudication_status")) != "ADJUDICATED":
            errors.append(
                {"type": "unadjudicated_final_label", "document_id": document_id}
            )
        review_status = text(event.get("review_status"))
        if review_status not in REVIEW_STATUSES:
            errors.append({"type": "invalid_review_status", "document_id": document_id})
        for field in (
            "source_review_status",
            "license_review_status",
            "quiz_suitability",
        ):
            if text(event.get(field)) not in QUALITY_REVIEW_STATUSES:
                errors.append(
                    {
                        "type": "invalid_quality_review_status",
                        "document_id": document_id,
                        "field": field,
                    }
                )
        if final_label and not text(event.get("reason")):
            errors.append(
                {"type": "adjudication_reason_missing", "document_id": document_id}
            )
        if final_label and not evidence_matches(
            template.get("content", ""), text(event.get("evidence_quote"))
        ):
            errors.append(
                {"type": "adjudication_evidence_missing", "document_id": document_id}
            )
    split_hashes: dict[str, set[str]] = defaultdict(set)
    for row in template_rows:
        split_hashes[row.get("split", "")].add(row.get("content_hash", ""))
    leakage = sorted(
        split_hashes.get("development", set()) & split_hashes.get("test", set()) - {""}
    )
    for content_hash in leakage:
        errors.append(
            {
                "type": "development_test_content_hash_leakage",
                "content_hash": content_hash,
            }
        )
    return {
        "status": "PASS" if not errors else "FAIL",
        "template_count": len(template_rows),
        "history_event_count": len(history),
        "error_count": len(errors),
        "errors": errors,
        "final_gold_ready_count": len(latest_adjudications(history)),
        "gold_is_not_auto_approved": True,
    }
