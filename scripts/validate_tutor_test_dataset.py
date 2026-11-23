#!/usr/bin/env python3
"""Validate tutor scenarios without changing source data or the database."""

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
from app.evaluation.tutor_dataset import validate_tutor_dataset  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "input",
        type=Path,
        default=ROOT / "data" / "evaluation" / "tutor_test_100.jsonl",
        nargs="?",
    )
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports" / "evaluation" / "dataset_validation_report.md",
    )
    return parser


def read_rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"row {line_number} must be a JSON object")
            rows.append(row)
    return rows


def render_report(path: Path, validation: dict, input_path: Path) -> None:
    candidate_status = json.dumps(
        validation["candidate_evidence_approval_status_counts"],
        ensure_ascii=False,
    )
    lines = [
        "# Tutor 평가 데이터셋 검증 보고서",
        "",
        f"- 생성 시각: {datetime.now(timezone.utc).isoformat()}",
        f"- 입력: `{input_path}`",
        f"- 구조 검증: `{'PASS' if validation['valid'] else 'FAIL'}`",
        f"- 점수화 준비: `{'READY' if validation['ready_for_scoring'] else 'BLOCKED'}`",
        "",
        "## 분포",
        "",
        f"- 전체 건수: {validation['row_count']}",
        f"- 기관별: `{json.dumps(validation['source_counts'], ensure_ascii=False)}`",
        "- 난이도별: "
        f"`{json.dumps(validation['difficulty_counts'], ensure_ascii=False)}`",
        "- 유형별: "
        f"`{json.dumps(validation['scenario_type_counts'], ensure_ascii=False)}`",
        "- 검수 상태별: "
        f"`{json.dumps(validation['gold_status_counts'], ensure_ascii=False)}`",
        "",
        "## 근거·계보 검증",
        "",
        f"- approvedEvidence 건수: {validation['approved_evidence_count']}",
        f"- 후보 근거 승인 상태: `{candidate_status}`",
        f"- conceptCode 누락: {validation['concept_code_missing_count']}건",
        f"- 개인정보 탐지: {validation['privacy_findings']}건",
        "",
        "## 오류",
        "",
    ]
    lines.extend(f"- {error}" for error in validation["errors"] or ["없음"])
    lines.extend(["", "## 주의 및 미완료 입력", ""])
    lines.extend(f"- {warning}" for warning in validation["warnings"] or ["없음"])
    lines.extend(
        [
            "",
            "## 정책",
            "",
            "- PENDING_REVIEW 행은 최종 모델 품질 점수에서 제외한다.",
            "- `expectedConcepts`, `expectedMisconception`, "
            "`expectedTeachingBehavior`, `goldStatus`는 모델 입력에서 제외한다.",
            "- source review/license/concept mapping이 승인되기 전에는 "
            "approvedEvidence로 승격하지 않는다.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    args = build_parser().parse_args()
    rows = read_rows(args.input)
    documents, _ = load_corpus(args.data_dir)
    validation = validate_tutor_dataset(rows, documents)
    render_report(args.report, validation, args.input)
    print(json.dumps(validation, ensure_ascii=False, indent=2))
    return 0 if validation["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
