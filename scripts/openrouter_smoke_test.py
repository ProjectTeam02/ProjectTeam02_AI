#!/usr/bin/env python3
"""Make one explicit, non-Gold OpenRouter connectivity smoke request."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from app.core.config import Settings  # noqa: E402
from app.model_comparison.openrouter_catalog import (  # noqa: E402
    OpenRouterCatalogClient,
)
from app.rag.indexing.llm_factory import LLMFactory  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="openai/gpt-5.4-mini")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="make the real OpenRouter request; default is catalog-only dry-run",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "model_comparison" / "openrouter_smoke.json",
    )
    parser.add_argument("--timeout", type=float, default=None)
    parser.add_argument("--max-cost-usd", type=float, default=0.05)
    return parser


def _usage(response) -> dict | None:
    raw = getattr(response, "raw", None)
    usage = getattr(raw, "usage", None)
    if usage is None and isinstance(raw, dict):
        usage = raw.get("usage")
    if hasattr(usage, "model_dump"):
        return usage.model_dump()
    return dict(usage) if isinstance(usage, dict) else None


async def run(args: argparse.Namespace) -> dict:
    catalog_client = OpenRouterCatalogClient(timeout_seconds=args.timeout or 10.0)
    metadata = (await catalog_client.fetch([args.model]))[args.model]
    if not metadata.available:
        result = {
            "schemaVersion": 1,
            "status": "MODEL_UNAVAILABLE",
            "modelId": args.model,
            "reason": metadata.reason,
            "catalog": metadata.as_dict(),
            "goldEvaluation": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result
    if not args.execute:
        result = {
            "schemaVersion": 1,
            "status": "DRY_RUN",
            "modelId": args.model,
            "catalog": metadata.as_dict(),
            "responseStored": False,
            "goldEvaluation": False,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return result
    if args.max_cost_usd <= 0:
        raise ValueError("--max-cost-usd must be greater than zero")
    base_settings = Settings()
    settings = base_settings.model_copy(
        update={"llm_provider": "openrouter", "llm_model": args.model}
    )
    timeout = args.timeout or settings.llm_timeout_seconds
    llm = LLMFactory(settings).create(set(metadata.supported_parameters))
    if llm is None:
        raise RuntimeError("OpenRouter LLM is disabled")
    prompt = (
        "This is an infrastructure smoke test, not a tutoring evaluation. "
        "Reply with exactly SMOKE_OK and no other text."
    )
    started = time.perf_counter()
    response = await asyncio.wait_for(llm.acomplete(prompt), timeout=timeout)
    elapsed_ms = max(0, round((time.perf_counter() - started) * 1000))
    text = str(getattr(response, "text", response)).strip()
    result = {
        "schemaVersion": 1,
        "status": "PASS" if text == "SMOKE_OK" else "UNEXPECTED_RESPONSE",
        "modelId": args.model,
        "latencyMs": elapsed_ms,
        "usage": _usage(response),
        "responseStored": False,
        "goldEvaluation": False,
        "catalog": metadata.as_dict(),
        "generation": None,
    }
    raw = getattr(response, "raw", None)
    generation_id = raw.get("id") if isinstance(raw, dict) else None
    if isinstance(generation_id, str) and generation_id:
        result["generation"] = await catalog_client.fetch_generation(generation_id)
    usage = result.get("usage") or {}
    input_tokens = usage.get("prompt_tokens") or usage.get("input_tokens")
    output_tokens = usage.get("completion_tokens") or usage.get("output_tokens")
    cost = None
    if input_tokens is not None and output_tokens is not None:
        cost = round(
            input_tokens / 1_000_000 * (metadata.input_price_per_million or 0)
            + output_tokens / 1_000_000 * (metadata.output_price_per_million or 0),
            8,
        )
    result["estimatedCostUsd"] = cost
    if cost is not None and cost > args.max_cost_usd:
        result["status"] = "COST_LIMIT_EXCEEDED"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    result = asyncio.run(run(build_parser().parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] in {"PASS", "DRY_RUN"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
