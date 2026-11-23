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
from app.rag.indexing.llm_factory import LLMFactory  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="openai/gpt-5.4-mini")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports" / "model_comparison" / "openrouter_smoke.json",
    )
    parser.add_argument("--timeout", type=float, default=None)
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
    base_settings = Settings()
    settings = base_settings.model_copy(
        update={"llm_provider": "openrouter", "llm_model": args.model}
    )
    timeout = args.timeout or settings.llm_timeout_seconds
    llm = LLMFactory(settings).create()
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
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> int:
    result = asyncio.run(run(build_parser().parse_args()))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
