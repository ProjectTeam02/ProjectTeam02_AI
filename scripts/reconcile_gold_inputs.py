"""Reconcile the current 320-row Gold queue with legacy review templates.

This report is metadata-only. It never copies labels or document content and
does not modify any input template.
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_QUEUE = ROOT / "data/labeled/precision/independent_gold_review_queue.csv"
DEFAULT_KDI = ROOT / "reports/step3/kdi_independent_gold_review_template.csv"
DEFAULT_BOK = ROOT / "reports/step3/bok_independent_gold_review_template.csv"
DEFAULT_JSON = ROOT / "reports/gold_template_reconciliation.json"
DEFAULT_MD = ROOT / "reports/gold_template_reconciliation.md"


def _read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _source(row: dict[str, str]) -> str:
    return (row.get("source") or row.get("source_group") or "").strip()


def _metadata(path: Path, rows: list[dict[str, str]]) -> dict[str, Any]:
    ids = [row.get("document_id", "").strip() for row in rows]
    source_counts = Counter(_source(row) for row in rows)
    duplicate_ids = sorted(
        document_id
        for document_id, count in Counter(item for item in ids if item).items()
        if count > 1
    )
    return {
        "path": str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path),
        "row_count": len(rows),
        "source_counts": dict(source_counts),
        "unique_document_id_count": len(set(item for item in ids if item)),
        "duplicate_document_ids": duplicate_ids,
    }


def run(
    queue_path: Path = DEFAULT_QUEUE,
    kdi_path: Path = DEFAULT_KDI,
    bok_path: Path = DEFAULT_BOK,
    json_path: Path = DEFAULT_JSON,
    markdown_path: Path = DEFAULT_MD,
) -> dict[str, Any]:
    queue = _read(queue_path)
    kdi = _read(kdi_path)
    bok = _read(bok_path)
    queue_meta = _metadata(queue_path, queue)
    kdi_meta = _metadata(kdi_path, kdi)
    bok_meta = _metadata(bok_path, bok)
    source_counts = queue_meta["source_counts"]
    canonical_ok = (
        queue_meta["row_count"] == 320
        and source_counts == {"KDI": 160, "BOK": 160}
        and not queue_meta["duplicate_document_ids"]
    )
    report: dict[str, Any] = {
        "status": "PASS" if canonical_ok else "FAIL",
        "canonical_input": queue_meta,
        "canonical_policy": "KDI160+BOK160=320; current queue only",
        "legacy_inputs": {
            "kdi_template": {
                **kdi_meta,
                "status": "LEGACY_EXCLUDED_SOURCE_MISMATCH"
                if kdi_meta["source_counts"] != {"KDI": 160}
                else "LEGACY_EXCLUDED",
            },
            "bok_template": {**bok_meta, "status": "LEGACY_EXCLUDED"},
        },
        "mixing_prevented": True,
        "gold_labels_copied_or_approved": False,
        "notes": [
            "과거 KDI 160+BOK 205 템플릿은 현재 320건 평가 입력에서 제외한다.",
            (
                "레거시 KDI 템플릿의 실제 source가 BOK로 기록된 경우 "
                "source mismatch로 표시한다."
            ),
            "독립 검수 승인 전에는 최종 Gold 및 P/R/F1을 생성하지 않는다.",
        ],
    }
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(
        "# Gold 입력 템플릿 조정 보고서\n\n"
        f"- 상태: **`{report['status']}`**\n"
        "- 현재 기준: **KDI 160 + BOK 160 = 320건**\n"
        f"- 현재 큐: `{queue_meta['path']}` ({queue_meta['row_count']}건, "
        f"기관별 `{queue_meta['source_counts']}`)\n"
        f"- 과거 KDI 템플릿: `{kdi_meta['path']}` ({kdi_meta['row_count']}건, "
        f"기관별 `{kdi_meta['source_counts']}`) → **LEGACY_EXCLUDED**\n"
        f"- 과거 BOK 템플릿: `{bok_meta['path']}` ({bok_meta['row_count']}건, "
        f"기관별 `{bok_meta['source_counts']}`) → **LEGACY_EXCLUDED**\n\n"
        "현재 검수 CLI와 Gold 조립 스크립트의 기본 입력은 현재 320건 큐이며, "
        "과거 템플릿은 명시적인 레거시 점검 시에만 사용할 수 있습니다.\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--kdi", type=Path, default=DEFAULT_KDI)
    parser.add_argument("--bok", type=Path, default=DEFAULT_BOK)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MD)
    args = parser.parse_args()
    print(
        json.dumps(
            run(args.queue, args.kdi, args.bok, args.json, args.markdown),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
