from __future__ import annotations

import json

from app.rag.harness import aggregate_stage_timings
from scripts.summarize_tutor_latency import parse_latency_lines, summarize


def test_stage_timings_map_safe_rag_trace_and_counts_retries():
    assert aggregate_stage_timings(
        [
            {"stage": "query_rewriting", "latency_ms": 4},
            {"stage": "retrieval", "latency_ms": 10},
            {"stage": "retrieval", "latency_ms": 3, "status": "error"},
            {"stage": "context", "latency_ms": 2},
            {"stage": "groundedness_validation", "latency_ms": 1},
            {"stage": "blocked", "latency_ms": 999},
        ]
    ) == {
        "query_rewrite_ms": 4,
        "retrieval_ms": 13,
        "context_build_ms": 2,
        "grounding_ms": 1,
    }


def test_latency_summary_reports_missing_stages_as_unmeasured():
    lines = [
        'INFO tutor_latency '
        + json.dumps(
            {
                "event": "tutor_latency",
                "request_id": "r1",
                "status": "completed",
                "end_to_end_ms": 100,
                "retrieval_ms": 20,
                "stage_statuses": {"retrieval_ms": "ok"},
            }
        ),
        json.dumps(
            {
                "event": "tutor_latency",
                "requestId": "r1",
                "status": "completed",
                "end_to_end_ms": 150,
                "backend_save_ms": 30,
                "stage_statuses": {"backend_save_ms": "ok"},
            }
        ),
        json.dumps(
            {
                "event": "tutor_latency",
                "request_id": "r2",
                "status": "failed",
                "end_to_end_ms": 200,
            }
        ),
    ]
    result = summarize(parse_latency_lines(lines))
    assert result["request_count"] == 2
    assert result["failure_rate"] == 0.5
    assert result["metrics"]["end_to_end_ms"]["p95_ms"] == 200
    assert result["metrics"]["retrieval_ms"]["sample_count"] == 1
    assert result["metrics"]["retrieval_ms"]["failure_rate"] == 0.0
    assert result["metrics"]["end_to_end_ms"]["failure_rate"] is None
    assert result["metrics"]["llm_generation_ms"]["p95_ms"] is None
