#!/usr/bin/env python3
"""Compare tutor Context A/B/C with the same model harness and cases."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.tutor_gold import validate_tutor_gold  # noqa: E402
from app.model_comparison.catalog import select_models  # noqa: E402
from app.model_comparison.openrouter_catalog import (  # noqa: E402
    OpenRouterCatalogClient,
)
from app.model_comparison.runner import (  # noqa: E402
    ComparisonBudget,
    ModelComparisonRunner,
)
from scripts.validate_tutor_gold import read_jsonl  # noqa: E402

VARIANTS = ("A", "B", "C")
PROFILE_FIELDS = {
    "conceptCode",
    "accuracyRate",
    "recentIncorrectCount",
    "estimatedMastery",
    "weaknessScore",
    "lastStudiedAt",
    "currentStageId",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--stage", choices=("mock", "interim", "final"), default="mock"
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument("--max-calls", type=int, default=None)
    parser.add_argument("--max-cost-usd", type=float, default=1.0)
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument("--min-interval-ms", type=float, default=0.0)
    parser.add_argument("--model", action="append", dest="models")
    return parser


def _context_case_payload(row: dict[str, Any], variant: str) -> dict[str, Any]:
    history = row.get("conversationHistory", []) if variant in {"B", "C"} else []
    concept_code = row.get("conceptCode")
    payload: dict[str, Any] = {
        "caseId": f"{row.get('caseId')}::context-{variant}",
        "question": row.get("studentQuestion"),
        "history": history,
        "learningConcept": concept_code,
        "conceptCodes": [concept_code] if concept_code else [],
        "corpus": row.get("approvedEvidence", []),
        "contextVariant": variant,
    }
    if variant == "C":
        profile = row.get("learnerProfile")
        if isinstance(profile, dict):
            safe_profile = {
                key: value for key, value in profile.items() if key in PROFILE_FIELDS
            }
            payload["personalizedContext"] = {"learnerProfile": safe_profile}
        graph = row.get("approvedPrerequisiteConcepts", [])
        if graph:
            payload.setdefault("personalizedContext", {})[
                "conceptGraphContext"
            ] = {
                "currentConceptCode": concept_code,
                "prerequisiteConcepts": graph,
            }
    return payload


async def run(args: argparse.Namespace) -> int:
    if args.execute and args.stage == "mock":
        raise SystemExit("--execute requires --stage interim or final")
    if not args.execute and args.stage != "mock":
        raise SystemExit("interim/final context comparison requires --execute")
    if args.max_cases is not None and args.max_cases <= 0:
        raise SystemExit("--max-cases must be greater than zero")
    if args.max_calls is not None and args.max_calls <= 0:
        raise SystemExit("--max-calls must be greater than zero")
    if args.max_cost_usd <= 0:
        raise SystemExit("--max-cost-usd must be greater than zero")
    if args.max_retries < 0:
        raise SystemExit("--max-retries must not be negative")
    if args.min_interval_ms < 0:
        raise SystemExit("--min-interval-ms must not be negative")
    rows = read_jsonl(args.input)
    if args.stage in {"interim", "final"}:
        validation, _ = validate_tutor_gold(
            rows, require_full_dataset=args.stage == "final"
        )
        if not validation["readyForScoring"]:
            raise SystemExit(f"Gold is not ready for context stage: {args.stage}")
    cases = []
    for row in rows[: args.max_cases] if args.max_cases else rows:
        for variant in VARIANTS:
            cases.extend(load_cases_from_payload(_context_case_payload(row, variant)))
    specs = select_models(args.models)
    metadata = {}
    if args.execute:
        metadata = await OpenRouterCatalogClient().fetch(
            [spec.model_id for spec in specs]
        )
    max_calls = args.max_calls or len(specs) * len(cases)
    budget = ComparisonBudget(
        max_calls=max_calls if args.execute else None,
        max_cost_usd=args.max_cost_usd if args.execute else None,
        max_retries=max(0, args.max_retries),
        min_interval_seconds=max(0.0, args.min_interval_ms / 1000),
    )
    runner = ModelComparisonRunner(
        model_specs=specs, model_metadata=metadata, budget=budget
    )
    run_label = (
        "mock"
        if args.stage == "mock"
        else "interim"
        if args.stage == "interim"
        else "final"
    )
    results = await runner.run(
        cases,
        str(args.output),
        execute=args.execute,
        max_cases=None,
        run_label=run_label,
    )
    print(
        f"completed {len(results)} context result(s); "
        f"stage={args.stage}, variants={','.join(VARIANTS)}"
    )
    return 0


def load_cases_from_payload(payload: dict[str, Any]):
    """Keep ComparisonCase parsing identical to the normal model harness."""

    from app.model_comparison.contracts import ComparisonCase

    return [ComparisonCase.from_dict(payload)]


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
