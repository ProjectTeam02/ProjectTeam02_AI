#!/usr/bin/env python3
"""Compare the fixed OpenRouter tutor models using a JSONL case set.

The default mode is deterministic and offline. Add ``--execute`` only for an
explicit live OpenRouter run; the key is read from ``OPENROUTER_API_KEY``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Allow the documented ``python scripts/compare_tutor_models.py`` invocation
# to import the application package from the repository root.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.tutor_gold import validate_tutor_gold
from app.model_comparison.catalog import select_models
from app.model_comparison.io import load_cases, write_template
from app.model_comparison.openrouter_catalog import OpenRouterCatalogClient
from app.model_comparison.runner import ComparisonBudget, ModelComparisonRunner
from scripts.validate_tutor_gold import read_jsonl


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", nargs="?", help="input cases JSONL")
    parser.add_argument(
        "--output",
        default="reports/model_comparison/results.jsonl",
        help="append-only result JSONL path",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="enable real OpenRouter calls; disabled by default",
    )
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="restrict the run to one or more catalog model IDs",
    )
    parser.add_argument("--max-cases", type=int, default=None)
    parser.add_argument(
        "--max-calls",
        type=int,
        default=None,
        help="maximum provider attempts, including bounded retries",
    )
    parser.add_argument(
        "--max-cost-usd",
        type=float,
        default=1.0,
        help="hard estimated cost ceiling for live calls (default: 1.0)",
    )
    parser.add_argument("--max-retries", type=int, default=0)
    parser.add_argument(
        "--min-interval-ms",
        type=float,
        default=0.0,
        help="minimum delay between provider attempts",
    )
    parser.add_argument(
        "--catalog-output",
        type=Path,
        default=Path("reports/model_comparison/openrouter_catalog.json"),
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="rerun rows already completed in the same mode",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help=(
            "run a small operational smoke batch without treating it as final "
            "Gold evaluation"
        ),
    )
    parser.add_argument(
        "--init-template",
        metavar="PATH",
        help="create a fillable template instead of running a batch",
    )
    parser.add_argument("--count", type=int, default=100)
    return parser


async def run(args: argparse.Namespace) -> int:
    if args.init_template:
        write_template(args.init_template, args.count)
        print(f"created {args.count} case template rows: {args.init_template}")
        return 0
    if not args.input:
        raise SystemExit("input JSONL is required unless --init-template is used")
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
    if args.smoke_test and not args.execute:
        raise SystemExit("--smoke-test requires --execute for an OpenRouter smoke run")
    if args.execute and not args.smoke_test:
        validation, _ = validate_tutor_gold(read_jsonl(Path(args.input)))
        if not validation["readyForScoring"]:
            raise SystemExit(
                "Gold is not independent-approved; run scripts/validate_tutor_gold.py "
                "and complete human adjudication before the final benchmark"
            )
    cases = load_cases(args.input)
    specs = select_models(args.models)
    metadata = {}
    if args.execute:
        try:
            metadata = await OpenRouterCatalogClient().fetch(
                [spec.model_id for spec in specs]
            )
        except Exception as exc:
            raise SystemExit(
                f"OpenRouter catalog lookup failed: {type(exc).__name__}"
            ) from exc
        args.catalog_output.parent.mkdir(parents=True, exist_ok=True)
        args.catalog_output.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "models": {
                        model_id: item.as_dict()
                        for model_id, item in metadata.items()
                    },
                    "noAutomaticReplacement": True,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    max_cases = args.max_cases
    if args.smoke_test and max_cases is None:
        max_cases = 1
    call_limit = args.max_calls
    if call_limit is None:
        call_limit = len(specs) * (max_cases or len(cases))
    budget = ComparisonBudget(
        max_calls=call_limit if args.execute else None,
        max_cost_usd=args.max_cost_usd if args.execute else None,
        max_retries=max(0, args.max_retries),
        min_interval_seconds=max(0.0, args.min_interval_ms / 1000),
    )
    runner = ModelComparisonRunner(
        model_specs=specs, model_metadata=metadata, budget=budget
    )
    results = await runner.run(
        cases,
        args.output,
        execute=args.execute,
        resume=not args.no_resume,
        max_cases=max_cases,
        run_label="smoke" if args.smoke_test else None,
    )
    counts: dict[str, int] = {}
    for result in results:
        counts[result.status] = counts.get(result.status, 0) + 1
    mode = "smoke" if args.smoke_test else ("live" if args.execute else "mock")
    print(
        f"completed {len(results)} new {mode} result(s) for "
        f"{len(specs)} model(s); {counts or 'all rows already complete'}"
    )
    print(f"results: {Path(args.output)}")
    return 0


def main() -> int:
    return asyncio.run(run(build_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
