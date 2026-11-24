#!/usr/bin/env python3
"""Advance tutor Gold review without mutating the source dataset.

Examples:

    # Inspect and prepare a reviewer queue
    .venv/bin/python scripts/tutor_gold_workflow.py --prepare

    # Record a human review event (the evidence JSON is supplied by the reviewer)
    .venv/bin/python scripts/tutor_gold_workflow.py --record-review \
      --case-id TUTOR-001 --reviewer-id reviewer-a --status IN_REVIEW \
      --지decision IN_REVIEW --notes "개념과 근거를 확인 중"

    # After two independent APPROVE events, record adjudication
    .venv/bin/python scripts/tutor_gold_workflow.py --adjudicate \
      --case-id TUTOR-001 --reviewer-id adjudicator \
      --concept-code C0101 --approved-evidence evidence.json \
      --notes "두 검수자의 근거를 대조하여 승인"

The script does not infer concept codes, source approval, license approval, or
Gold status.  The original JSONL is read-only; events and interim projections
are separate local artifacts.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.tutor_review import (  # noqa: E402
    append_event,
    create_adjudication_event,
    create_review_event,
    load_canonical_concept_codes,
    project_approved_cases,
    read_jsonl,
    review_queue,
    workflow_summary,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "data/evaluation/tutor_test_100.jsonl",
    )
    parser.add_argument(
        "--history",
        type=Path,
        default=ROOT / "data/evaluation/tutor_gold_review_events.jsonl",
    )
    parser.add_argument(
        "--concept-master",
        type=Path,
        default=ROOT / "data/concept_master_1123.json",
    )
    parser.add_argument(
        "--queue-output",
        type=Path,
        default=ROOT / "data/evaluation/tutor_gold_review_queue.jsonl",
    )
    parser.add_argument(
        "--interim-output",
        type=Path,
        default=ROOT / "data/evaluation/tutor_interim_approved.jsonl",
    )
    parser.add_argument(
        "--status-output",
        type=Path,
        default=ROOT / "reports/evaluation/tutor_gold_workflow_status.json",
    )
    parser.add_argument("--prepare", action="store_true")
    parser.add_argument("--record-review", action="store_true")
    parser.add_argument("--adjudicate", action="store_true")
    parser.add_argument("--extract-interim", action="store_true")
    parser.add_argument("--case-id")
    parser.add_argument("--reviewer-id")
    parser.add_argument(
        "--status",
        choices=[
            "PENDING_REVIEW",
            "IN_REVIEW",
            "REVIEW_REQUIRED",
            "INDEPENDENT_APPROVED",
            "REJECTED",
        ],
        default="IN_REVIEW",
    )
    parser.add_argument(
        "--decision",
        choices=["IN_REVIEW", "REVIEW_REQUIRED", "APPROVE", "REJECT"],
        default="IN_REVIEW",
    )
    parser.add_argument("--concept-code")
    parser.add_argument(
        "--approved-evidence",
        type=Path,
        help="JSON file containing the reviewer-selected evidence list",
    )
    parser.add_argument("--notes", default="")
    parser.add_argument("--source-review-status", default="PENDING")
    parser.add_argument("--license-status", default="PENDING")
    return parser


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def _load_evidence(path: Path | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError("--approved-evidence JSON must be a list")
    return payload


def run(args: argparse.Namespace) -> dict[str, Any]:
    rows = read_jsonl(args.dataset)
    events = read_jsonl(args.history)
    canonical_codes = load_canonical_concept_codes(args.concept_master)
    by_case = {str(row.get("caseId")): row for row in rows}
    actions = sum(
        bool(value)
        for value in (
            args.prepare,
            args.record_review,
            args.adjudicate,
            args.extract_interim,
        )
    )
    if actions > 1:
        raise SystemExit(
            "prepare, record, adjudicate, and extract are mutually exclusive"
        )

    if args.record_review:
        case = by_case.get(str(args.case_id or ""))
        if case is None:
            raise SystemExit("--case-id does not exist in the dataset")
        event = create_review_event(
            case,
            reviewer_id=args.reviewer_id or "",
            status=args.status,
            decision=args.decision,
            notes=args.notes,
            concept_code=args.concept_code,
            approved_evidence=_load_evidence(args.approved_evidence),
            source_review_status=args.source_review_status,
            license_status=args.license_status,
            canonical_codes=canonical_codes,
        )
        append_event(args.history, event)
        events.append(event)
    elif args.adjudicate:
        case = by_case.get(str(args.case_id or ""))
        if case is None:
            raise SystemExit("--case-id does not exist in the dataset")
        prior = [event for event in events if event.get("caseId") == args.case_id]
        event = create_adjudication_event(
            case,
            adjudicator_id=args.reviewer_id or "",
            concept_code=args.concept_code or "",
            approved_evidence=_load_evidence(args.approved_evidence),
            notes=args.notes,
            reviewer_events=prior,
            source_review_status=args.source_review_status,
            license_status=args.license_status,
            canonical_codes=canonical_codes,
        )
        append_event(args.history, event)
        events.append(event)

    if args.prepare:
        _write_jsonl(
            args.queue_output,
            review_queue(rows, events, canonical_codes=canonical_codes),
        )
    if args.extract_interim:
        approved, projection = project_approved_cases(
            rows, events, canonical_codes=canonical_codes
        )
        if approved:
            _write_jsonl(args.interim_output, approved)
        elif args.interim_output.exists():
            raise SystemExit(
                "no human-adjudicated cases are available; existing interim output "
                "was not overwritten"
            )
        summary = workflow_summary(rows, events, canonical_codes=canonical_codes)
        summary["interimProjection"] = projection
        _write_json(args.status_output, summary)
        return summary

    summary = workflow_summary(rows, events, canonical_codes=canonical_codes)
    if args.prepare:
        summary["queueOutput"] = str(args.queue_output)
    _write_json(args.status_output, summary)
    return summary


def main() -> int:
    result = run(build_parser().parse_args())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("valid", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
