"""Summarize safe tutor latency log records.

The input may contain Backend JSON lines or AI lines with a ``tutor_latency``
JSON payload. It never needs request content and prints only aggregate timing
and failure data. Use a copied staging log, not a production log containing
unreviewed sensitive data.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

METRICS = (
    "backend_context_ms",
    "query_rewrite_ms",
    "retrieval_ms",
    "related_retrieval_ms",
    "context_build_ms",
    "llm_generation_ms",
    "grounding_ms",
    "backend_save_ms",
    "end_to_end_ms",
)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def parse_latency_lines(lines: Iterable[str]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    marker = "tutor_latency "
    for line in lines:
        candidate = line.strip()
        if candidate.startswith("{"):
            payload = candidate
        elif marker in candidate:
            payload = candidate.split(marker, 1)[1].strip()
        else:
            continue
        try:
            value = json.loads(payload)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and value.get("event") == "tutor_latency":
            records.append(value)
    return records


def _merge_request_records(records: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge the AI and Backend records emitted for one request ID."""

    merged: dict[str, dict[str, Any]] = {}
    anonymous: list[dict[str, Any]] = []
    for row in records:
        request_id = row.get("request_id") or row.get("requestId")
        if not request_id:
            anonymous.append(dict(row))
            continue
        current = merged.setdefault(str(request_id), {})
        for key, value in row.items():
            if key == "end_to_end_ms" and isinstance(value, (int, float)):
                current[key] = max(current.get(key, value), value)
            elif key == "stage_statuses":
                current.setdefault(key, {}).update(value or {})
            elif key == "status":
                if value == "failed" or current.get(key) != "failed":
                    current[key] = value
            else:
                current[key] = value
    return [*merged.values(), *anonymous]


def summarize(records: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows = _merge_request_records(records)
    grouped: dict[str, list[float]] = defaultdict(list)
    stage_failures: dict[str, int] = defaultdict(int)
    stage_observations: dict[str, int] = defaultdict(int)
    for row in rows:
        for metric in METRICS:
            value = row.get(metric)
            if isinstance(value, (int, float)):
                grouped[metric].append(float(value))
            status = (row.get("stage_statuses") or {}).get(metric)
            if isinstance(status, str):
                stage_observations[metric] += 1
                if status in {"error", "timeout", "failed"}:
                    stage_failures[metric] += 1
    failed = sum(row.get("status") != "completed" for row in rows)
    summary: dict[str, Any] = {
        "request_count": len(rows),
        "failure_count": failed,
        "failure_rate": round(failed / len(rows), 4) if rows else None,
        "metrics": {},
    }
    for metric in METRICS:
        values = grouped[metric]
        summary["metrics"][metric] = {
            "sample_count": len(values),
            "p50_ms": _percentile(values, 0.50),
            "p95_ms": _percentile(values, 0.95),
            "failure_rate": (
                round(stage_failures[metric] / stage_observations[metric], 4)
                if stage_observations[metric]
                else None
            ),
        }
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("log", nargs="?", type=Path)
    args = parser.parse_args()
    lines = (
        args.log.read_text(encoding="utf-8").splitlines()
        if args.log
        else sys.stdin
    )
    print(
        json.dumps(
            summarize(parse_latency_lines(lines)), ensure_ascii=False, indent=2
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
