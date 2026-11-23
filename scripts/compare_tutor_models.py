#!/usr/bin/env python3
"""Compare the fixed OpenRouter tutor models using a JSONL case set.

The default mode is deterministic and offline. Add ``--execute`` only for an
explicit live OpenRouter run; the key is read from ``OPENROUTER_API_KEY``.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

# Allow the documented ``python scripts/compare_tutor_models.py`` invocation
# to import the application package from the repository root.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.evaluation.tutor_gold import validate_tutor_gold
from app.model_comparison.catalog import select_models
from app.model_comparison.io import load_cases, write_template
from app.model_comparison.runner import ModelComparisonRunner
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
    runner = ModelComparisonRunner(model_specs=specs)
    max_cases = args.max_cases
    if args.smoke_test and max_cases is None:
        max_cases = 1
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
