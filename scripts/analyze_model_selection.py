#!/usr/bin/env python3
"""Create an evidence-gated model selection record; never select from gaps."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from app.evaluation.model_selection import (  # noqa: E402
    analyze_model_selection,
    read_jsonl,
    render_report,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    evaluation = ROOT / "data" / "evaluation"
    parser.add_argument(
        "--dataset", type=Path, default=evaluation / "tutor_test_100.jsonl"
    )
    parser.add_argument(
        "--comparison", type=Path, default=evaluation / "tutor_model_results.jsonl"
    )
    parser.add_argument(
        "--quality", type=Path, default=evaluation / "tutor_quality_results.jsonl"
    )
    parser.add_argument(
        "--human-review",
        type=Path,
        default=evaluation / "tutor_human_review_anonymous.jsonl",
    )
    parser.add_argument(
        "--context", type=Path, default=evaluation / "tutor_context_abc_results.jsonl"
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        default=ROOT / "reports" / "model_selection_record.json",
    )
    parser.add_argument(
        "--report", type=Path, default=ROOT / "reports" / "model_selection_report.md"
    )
    return parser


def main() -> int:
    args = build_parser().parse_args()
    record = analyze_model_selection(
        comparison_rows=read_jsonl(args.comparison),
        quality_rows=read_jsonl(args.quality),
        dataset_rows=read_jsonl(args.dataset),
        human_review_rows=read_jsonl(args.human_review),
        context_rows=read_jsonl(args.context),
    )
    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(record), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
