#!/usr/bin/env python3
"""Fetch and record current OpenRouter metadata for the tutor candidates."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from app.model_comparison.catalog import MODEL_SPECS  # noqa: E402
from app.model_comparison.openrouter_catalog import (  # noqa: E402
    OpenRouterCatalogClient,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model",
        action="append",
        dest="models",
        help="model ID to inspect; defaults to the five catalog candidates",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "model_comparison" / "openrouter_catalog.json",
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    return parser


async def run(args: argparse.Namespace) -> dict:
    model_ids = args.models or [spec.model_id for spec in MODEL_SPECS]
    metadata = await OpenRouterCatalogClient(
        timeout_seconds=args.timeout
    ).fetch(model_ids)
    result = {
        "schemaVersion": 1,
        "source": "https://openrouter.ai/api/v1/models",
        "models": {model_id: item.as_dict() for model_id, item in metadata.items()},
        "availableModels": [
            model_id for model_id, item in metadata.items() if item.available
        ],
        "excludedModels": {
            model_id: item.reason
            for model_id, item in metadata.items()
            if not item.available
        },
        "noAutomaticReplacement": True,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    result = asyncio.run(run(build_parser().parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not result["excludedModels"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
