#!/usr/bin/env python3
"""Validate tutor Gold inputs and emit a non-approved human review queue."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from app.dataset_pipeline.io import load_corpus  # noqa: E402
from app.evaluation.tutor_gold import (  # noqa: E402
    load_concept_map,
    validate_tutor_gold,
)


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must contain an object")
            rows.append(value)
    return rows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        nargs="?",
        default=ROOT / "data" / "evaluation" / "tutor_test_100.jsonl",
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--concept-map", type=Path)
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports" / "evaluation" / "tutor_gold_validation_report.md",
    )
    parser.add_argument(
        "--json-report",
        type=Path,
        default=ROOT / "reports" / "evaluation" / "tutor_gold_validation.json",
    )
    parser.add_argument(
        "--review-queue",
        type=Path,
        default=ROOT / "data" / "evaluation" / "tutor_gold_review_queue.jsonl",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="write reports but return success while Gold is blocked",
    )
    return parser


def render_report(
    report_path: Path,
    input_path: Path,
    validation: dict,
    missing_inputs: list[str],
) -> None:
    lines = [
        "# Tutor Gold 검증 보고서",
        "",
        f"- 검증 시각: {datetime.now(timezone.utc).isoformat()}",
        f"- 입력: `{input_path}`",
        f"- 구조 검증: `{'PASS' if validation['validStructure'] else 'FAIL'}`",
        (
            f"- 최종 평가 사용 가능: `{
                'READY' if validation['readyForScoring'] else 'BLOCKED'
            }`"
        ),
        "- 자동 독립 승인 수행 여부: `False`",
        "",
        "## 현황",
        "",
        f"- 전체 건수: {validation['rowCount']}",
        f"- 상태별: `{json.dumps(validation['statusCounts'], ensure_ascii=False)}`",
        (
            "- 검수 큐 상태: `"
            f"{json.dumps(validation['reviewQueueStatusCounts'], ensure_ascii=False)}`"
        ),
        f"- conceptCode 누락: {validation['missingConceptCodeCount']}건",
        f"- approvedEvidence 포함 행: {validation['approvedEvidenceRowCount']}건",
        f"- 차단 finding: {validation['blockingFindingCount']}건",
        "",
        "## 미완료 입력",
        "",
    ]
    lines.extend(f"- {item}" for item in missing_inputs or ["없음"])
    lines.extend(["", "## 차단 사유 샘플", ""])
    for finding in validation["blockingFindings"][:30]:
        lines.append(f"- `{json.dumps(finding, ensure_ascii=False)}`")
    if len(validation["blockingFindings"]) > 30:
        lines.append(
            f"- 그 외 {len(validation['blockingFindings']) - 30}건은 JSON 보고서에 기록"
        )
    lines.extend(
        [
            "",
            "## 정책",
            "",
            "- REVIEW_REQUIRED 행은 정식 모델 비교·교육 품질 점수에 사용하지 않는다.",
            "- 출처 승인, 라이선스, 개념 코드, 독립 검수 이력은 사람이 확인해야 한다.",
            "- 정답 초안은 별도 검수 큐에만 기록하며 Gold 승인으로 간주하지 않는다.",
            "- 원본 JSON/JSONL과 운영 DB는 수정하지 않았다.",
        ]
    )
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = build_parser().parse_args()
    rows = read_jsonl(args.input)
    documents = []
    source_error = None
    try:
        documents, _ = load_corpus(args.data_dir)
    except FileNotFoundError as exc:
        source_error = str(exc)
    concept_map = {}
    if args.concept_map:
        concept_map = load_concept_map(
            json.loads(args.concept_map.read_text(encoding="utf-8"))
        )
    validation, queue = validate_tutor_gold(
        rows, documents=documents, concept_map=concept_map
    )
    missing_inputs = []
    if source_error:
        missing_inputs.append(source_error)
    if not args.concept_map:
        missing_inputs.append("canonical Backend conceptCode mapping file")
    if not validation["readyForScoring"]:
        missing_inputs.append("independent human review and adjudication")
    if not validation["approvedEvidenceRowCount"]:
        missing_inputs.append("approved evidence with confirmed source/license status")
    if source_error:
        validation["sourceLoadError"] = source_error
    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.review_queue.parent.mkdir(parents=True, exist_ok=True)
    args.review_queue.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in queue),
        encoding="utf-8",
    )
    render_report(args.report, args.input, validation, missing_inputs)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["readyForScoring"] or args.report_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
