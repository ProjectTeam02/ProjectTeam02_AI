"""Assemble human-approved review templates into the comparison Gold CSV.

이 스크립트는 라벨을 만들지 않습니다. 모든 test 행에 사람이 입력한
최종 라벨과 독립 검수 상태가 있을 때만 `independent_gold_test.csv`를
생성합니다. 아직 PENDING 행이 있으면 상태 보고서만 만들고 평가 입력은
생성하지 않습니다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_KDI = ROOT / "reports/step3/kdi_independent_gold_review_template.csv"
DEFAULT_BOK = ROOT / "reports/step3/bok_independent_gold_review_template.csv"
DEFAULT_OUTPUT = ROOT / "reports/independent_gold_test.csv"
DEFAULT_STATUS = ROOT / "reports/independent_gold_assembly_status.json"
DEFAULT_HISTORY = ROOT / "data/labeled/precision/gold_review_history.jsonl"
VALID_SCORES = {"0", "1", "2"}
VALID_MODES = {"ADJUDICATED_CONSENSUS", "THIRD_PARTY_REVIEW"}


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _text(value: object) -> str:
    text = "" if value is None else str(value).strip()
    return "" if text.casefold() in {"", "null", "none", "nan"} else text


def _path_label(path: Path) -> str:
    """Show repository-relative paths when possible, including relative inputs."""
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(ROOT))
    except ValueError:
        return str(path)


def _ready_test_row(row: dict[str, str]) -> list[str]:
    """Return explicit validation failures for one test row."""
    failures: list[str] = []
    if _text(row.get("final_gold")) not in VALID_SCORES:
        failures.append("final_gold")
    if _text(row.get("review_status")) != "APPROVED":
        failures.append("review_status")
    if _text(row.get("gold_set_status")) != "INDEPENDENT_APPROVED":
        failures.append("gold_set_status")
    if not _text(row.get("content_hash")):
        failures.append("content_hash")
    mode = _text(row.get("review_mode"))
    if mode not in VALID_MODES:
        failures.append("review_mode")
    try:
        reviewer_count = int(_text(row.get("reviewer_count")))
    except ValueError:
        reviewer_count = 0
    if (mode == "ADJUDICATED_CONSENSUS" and reviewer_count < 2) or (
        mode == "THIRD_PARTY_REVIEW" and reviewer_count < 1
    ):
        failures.append("reviewer_count")
    if not _text(row.get("evidence_quote")):
        failures.append("evidence_quote")
    if not _text(row.get("reason")):
        failures.append("reason")
    return failures


def _to_gold_row(row: dict[str, str]) -> dict[str, str]:
    """Map the reviewer-facing names to compare_precision_methods' contract."""
    output = dict(row)
    output["source_group"] = _text(row.get("source"))
    output["gold_score"] = _text(row.get("final_gold"))
    return output


def run(
    kdi_path: Path = DEFAULT_KDI,
    bok_path: Path = DEFAULT_BOK,
    output_path: Path = DEFAULT_OUTPUT,
    status_path: Path = DEFAULT_STATUS,
    history_path: Path | None = None,
) -> dict[str, Any]:
    rows = _read(kdi_path) + _read(bok_path)
    history_validation: dict[str, Any] | None = None
    if history_path is not None:
        from app.dataset_pipeline import gold_review

        history = gold_review.load_history(history_path)
        history_validation = gold_review.validate_history(rows, history)
        rows = gold_review.build_gold_template_rows(rows, history)
    duplicate_ids = sorted(
        document_id
        for document_id, count in Counter(
            _text(row.get("document_id")) for row in rows
        ).items()
        if document_id and count > 1
    )
    test_rows = [row for row in rows if _text(row.get("split")) == "test"]
    failures: dict[str, list[str]] = {}
    for row in test_rows:
        row_failures = _ready_test_row(row)
        if row_failures:
            failures[_text(row.get("document_id"))] = row_failures
    ready = (
        bool(test_rows)
        and not duplicate_ids
        and not failures
        and (history_validation is None or history_validation["status"] == "PASS")
    )
    status = {
        "status": "READY" if ready else "NOT_READY",
        "template_row_count": len(rows),
        "test_row_count": len(test_rows),
        "pending_or_invalid_test_count": len(failures),
        "pending_or_invalid_test_ids": sorted(failures)[:100],
        "duplicate_document_ids": duplicate_ids,
        "history_validation": history_validation,
        "gold_values_created_automatically": False,
        "output_path": _path_label(output_path),
        "review_history_path": (
            _path_label(history_path) if history_path is not None else None
        ),
        "reason": (
            "모든 test 행이 독립 검수 승인을 충족했습니다."
            if ready
            else (
                "test 행의 사람 검수·합의가 완료되기 전에는 "
                "Gold CSV를 생성하지 않습니다."
            )
        ),
    }
    status_path.parent.mkdir(parents=True, exist_ok=True)
    status_path.write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if ready:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_rows = [_to_gold_row(row) for row in rows]
        fields = list(output_rows[0])
        with output_path.open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(output_rows)
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kdi", type=Path, default=DEFAULT_KDI)
    parser.add_argument("--bok", type=Path, default=DEFAULT_BOK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument(
        "--history",
        type=Path,
        default=None,
        help="로컬 사람 검수 append-only JSONL을 템플릿에 반영합니다.",
    )
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.kdi, args.bok, args.output, args.status, args.history),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
