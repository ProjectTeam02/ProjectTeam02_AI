#!/usr/bin/env python3
"""Evaluate model-comparison answers with the human-review-first 60-point rubric."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.evaluation.tutor_quality import (  # noqa: E402
    DEFAULT_JUDGE_MODEL,
    MockJudgeClient,
    OpenRouterJudgeClient,
    deduction_report,
    evaluate_comparison_result,
    tutor_quality_schema,
    write_jsonl,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset",
        type=Path,
        default=ROOT / "data" / "evaluation" / "tutor_test_100.jsonl",
    )
    parser.add_argument(
        "--results",
        type=Path,
        default=ROOT / "data" / "evaluation" / "tutor_model_results.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "evaluation" / "tutor_quality_results.jsonl",
    )
    parser.add_argument(
        "--human-review",
        type=Path,
        default=ROOT / "data" / "evaluation" / "tutor_human_review_anonymous.jsonl",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "reports" / "evaluation" / "tutor_quality_deduction_report.md",
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=ROOT / "reports" / "evaluation" / "tutor_quality_schema.json",
    )
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument(
        "--stage",
        choices=(
            "MOCK_TEST",
            "INTERIM_MODEL_COMPARISON",
            "FINAL_MODEL_EVALUATION",
        ),
        default=None,
        help="evaluation stage; interim scores remain PRELIMINARY",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="make live OpenRouter Judge calls; disabled by default",
    )
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-results", type=int, default=None)
    return parser


def read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSONL at {path}:{line_number}") from exc
            if not isinstance(row, dict):
                raise ValueError(f"JSONL row at {path}:{line_number} must be an object")
            rows.append(row)
    return rows


def _case_for_result(cases: dict[str, dict], result: dict) -> dict | None:
    case_id = result.get("case_id")
    case = cases.get(case_id)
    if case is not None:
        return case
    if isinstance(case_id, str) and "::context-" in case_id:
        return cases.get(case_id.split("::context-", 1)[0])
    return None


async def run(args: argparse.Namespace) -> int:
    for path in (args.output, args.human_review):
        if path.exists() and not args.force:
            raise SystemExit(f"refusing to overwrite {path}; use --force")
    cases = {row.get("caseId"): row for row in read_jsonl(args.dataset)}
    result_rows = read_jsonl(args.results)
    if args.max_results is not None:
        result_rows = result_rows[: args.max_results]
    settings = Settings(_env_file=None)
    evaluation_stage = args.stage
    if evaluation_stage is None:
        if result_rows and all(row.get("mode") == "mock" for row in result_rows):
            evaluation_stage = "MOCK_TEST"
        elif any(row.get("mode") == "interim" for row in result_rows):
            evaluation_stage = "INTERIM_MODEL_COMPARISON"
        else:
            evaluation_stage = "FINAL_MODEL_EVALUATION"
    judge = (
        OpenRouterJudgeClient(args.judge_model, settings=settings)
        if args.execute
        else MockJudgeClient()
    )
    evaluations: list[dict] = []
    human_rows: list[dict] = []
    for result in result_rows:
        case_id = result.get("case_id")
        case = _case_for_result(cases, result)
        if case is None:
            evaluations.append(
                {
                    "schemaVersion": 1,
                    "caseId": case_id,
                    "modelId": result.get("model_id"),
                    "contextVariant": result.get("context_variant"),
                    "evaluationStatus": "NOT_EVALUATED_UNKNOWN_CASE",
                    "evaluationStage": evaluation_stage,
                    "judgeModelId": judge.model_id,
                    "judgePromptVersion": "tutor-quality-judge-v1",
                    "accuracyScore": None,
                    "groundingScore": None,
                    "misconceptionScore": None,
                    "personalizationScore": None,
                    "pedagogyScore": None,
                    "totalEducationScore": None,
                    "deductions": [],
                    "criticalErrors": [
                        {
                            "code": "EVALUATION_INPUT_INVALID",
                            "severity": "high",
                            "detail": "model result has no matching evaluation case",
                        }
                    ],
                    "needsHumanReview": True,
                }
            )
            continue
        evaluation, human = await evaluate_comparison_result(
            case,
            result,
            judge,
            evaluation_stage=evaluation_stage,
        )
        evaluations.append(evaluation)
        human_rows.append(human)
    write_jsonl(args.output, evaluations)
    write_jsonl(args.human_review, human_rows)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(deduction_report(evaluations), encoding="utf-8")
    args.schema.parent.mkdir(parents=True, exist_ok=True)
    args.schema.write_text(
        json.dumps(tutor_quality_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    counts: dict[str, int] = {}
    for row in evaluations:
        status = str(row.get("evaluationStatus"))
        counts[status] = counts.get(status, 0) + 1
    print(
        json.dumps(
            {
                "evaluated": len(evaluations),
                "judgeMode": "live" if args.execute else "mock",
                "evaluationStage": evaluation_stage,
                "judgeModelId": judge.model_id,
                "statusCounts": counts,
                "output": str(args.output),
                "humanReview": str(args.human_review),
                "report": str(args.report),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
