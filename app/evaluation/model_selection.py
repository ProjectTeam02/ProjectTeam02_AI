"""Evidence-gated final tutor model selection.

This module never infers a winner from mock, incomplete, or unreviewed data.
It produces a decision record that can be used by deployment tooling without
silently turning a development run into a production model selection.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from app.model_comparison.catalog import MODEL_SPECS

EDUCATION_MAX = 60
OPERATIONS_MAX = 40
REQUIRED_CONTEXT_VARIANTS = {"A", "B", "C"}
APPROVED_GOLD = "INDEPENDENT_APPROVED"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                value = json.loads(line)
                if isinstance(value, dict):
                    rows.append(value)
    return rows


def _status_counts(rows: Iterable[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(row.get(key)) for row in rows))


def _model_summary(
    model_id: str,
    comparison_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    comparisons = [row for row in comparison_rows if row.get("model_id") == model_id]
    quality = [row for row in quality_rows if row.get("modelId") == model_id]
    live = [row for row in comparisons if row.get("mode") == "live"]
    successful_live = [row for row in live if row.get("status") == "ok"]
    scored = [
        row
        for row in quality
        if row.get("evaluationStatus") == "EVALUATED"
        and row.get("totalEducationScore") is not None
    ]
    latency = [
        float(row["latency_ms"])
        for row in successful_live
        if isinstance(row.get("latency_ms"), (int, float))
    ]
    costs = [
        float(row["estimated_cost_usd"])
        for row in successful_live
        if isinstance(row.get("estimated_cost_usd"), (int, float))
    ]
    return {
        "comparisonCount": len(comparisons),
        "comparisonStatusCounts": _status_counts(comparisons, "status"),
        "liveCount": len(live),
        "liveSuccessCount": len(successful_live),
        "qualityCount": len(quality),
        "scoredQualityCount": len(scored),
        "educationAverage": (
            round(
                sum(float(row["totalEducationScore"]) for row in scored)
                / len(scored),
                3,
            )
            if scored
            else None
        ),
        "actualCostUsd": round(sum(costs), 8) if costs else None,
        "ttftAvailable": any("ttft_ms" in row for row in successful_live),
        "latencySampleCount": len(latency),
        "latencyP50Ms": _percentile(latency, 0.50),
        "latencyP95Ms": _percentile(latency, 0.95),
    }


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def analyze_model_selection(
    *,
    comparison_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    dataset_rows: list[dict[str, Any]],
    human_review_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    model_ids = [spec.model_id for spec in MODEL_SPECS]
    summaries = {
        model_id: _model_summary(model_id, comparison_rows, quality_rows)
        for model_id in model_ids
    }
    expected_case_count = len(dataset_rows)
    expected_model_count = len(model_ids)
    quality_eligible = bool(dataset_rows) and all(
        row.get("goldStatus") == APPROVED_GOLD for row in dataset_rows
    ) and all(
        summaries[model_id]["scoredQualityCount"] == expected_case_count
        for model_id in model_ids
    )
    live_complete = all(
        summaries[model_id]["liveSuccessCount"] == expected_case_count
        and summaries[model_id]["ttftAvailable"]
        and summaries[model_id]["latencySampleCount"] == expected_case_count
        and summaries[model_id]["actualCostUsd"] is not None
        for model_id in model_ids
    )
    review_statuses_complete = all(
        str(row.get("reviewStatus", "")).upper()
        in {"APPROVED", "REVIEWED", "COMPLETED"}
        for row in human_review_rows
    )
    review_keys = [
        (row.get("reviewId"), row.get("modelId"), row.get("caseIdHash"))
        for row in human_review_rows
    ]
    human_complete = (
        expected_case_count > 0
        and len(human_review_rows) == expected_case_count * expected_model_count
        and len(set(review_keys)) == len(review_keys)
        and review_statuses_complete
        and all(
            row.get("humanTotalEducationScore") is not None
            for row in human_review_rows
        )
    )
    variants = {
        str(row.get("contextVariant", row.get("context_variant", ""))).upper()
        for row in context_rows
    }
    context_complete = REQUIRED_CONTEXT_VARIANTS <= variants
    gates = {
        "independentGold": bool(dataset_rows)
        and all(row.get("goldStatus") == APPROVED_GOLD for row in dataset_rows),
        "educationScores": quality_eligible,
        "liveOperations": live_complete,
        "humanReview": human_complete,
        "contextABC": context_complete,
    }
    ready = all(gates.values())
    return {
        "schemaVersion": 1,
        "decisionStatus": "READY" if ready else "NOT_READY",
        "primaryModel": None,
        "fallbackModel": None,
        "selectionRule": {
            "educationQualityMax": EDUCATION_MAX,
            "operationsEfficiencyMax": OPERATIONS_MAX,
            "totalMax": EDUCATION_MAX + OPERATIONS_MAX,
            "tiePolicy": "statistical uncertainty is a tie; do not force a winner",
        },
        "gates": gates,
        "missingEvidence": _missing_evidence(gates, comparison_rows, context_rows),
        "models": summaries,
        "inputCounts": {
            "dataset": len(dataset_rows),
            "comparison": len(comparison_rows),
            "quality": len(quality_rows),
            "humanReview": len(human_review_rows),
            "contextABC": len(context_rows),
        },
    }


def _missing_evidence(
    gates: dict[str, bool],
    comparison_rows: list[dict[str, Any]],
    context_rows: list[dict[str, Any]],
) -> list[str]:
    missing: list[str] = []
    if not gates["independentGold"]:
        missing.append("100개 사례의 INDEPENDENT_APPROVED Gold")
    if not gates["educationScores"]:
        missing.append("5개 모델 모두의 검수 Gold 기반 교육 품질 점수")
    if not gates["liveOperations"]:
        missing.append("5개 모델의 실제 live 비용·TTFT·p50/p95·성공률")
    if not gates["humanReview"]:
        missing.append("완료 상태의 익명 사람 검토 결과")
    if not gates["contextABC"]:
        missing.append("개인화 Context A/B/C 실험 결과")
    if not comparison_rows:
        missing.append("모델 비교 실행 결과 JSONL")
    if not context_rows:
        missing.append("Context A/B/C 결과 JSONL")
    return missing


def render_report(record: dict[str, Any]) -> str:
    lines = [
        "# 최종 튜터 모델 선정 보고서",
        "",
        f"- 결정 상태: `{record['decisionStatus']}`",
        "- 최종 기본 모델: 선정하지 않음",
        "- 최종 대체 모델: 선정하지 않음",
        "- 정책: 교육 품질 60점 + 운영 효율 40점",
        "",
        "## 모델별 실험 기록",
        "",
        (
            "| 모델 | 비교 건수 | Live 성공 | 교육 점수 건수 | 실제 비용(USD) "
            "| TTFT | p50/p95(ms) |"
        ),
        "|---|---:|---:|---:|---:|---|---|",
    ]
    for model_id, summary in record["models"].items():
        p50 = summary["latencyP50Ms"]
        p95 = summary["latencyP95Ms"]
        cost = summary["actualCostUsd"]
        cost_text = cost if cost is not None else "N/A"
        lines.append(
            f"| `{model_id}` | {summary['comparisonCount']} | "
            f"{summary['liveSuccessCount']} | {summary['scoredQualityCount']} | "
            f"{cost_text} "
            "| "
            f"{'yes' if summary['ttftAvailable'] else 'N/A'} | "
            f"{p50 if p50 is not None else 'N/A'}/{p95 if p95 is not None else 'N/A'} |"
        )
    lines.extend(["", "## 선정 게이트", ""])
    for name, passed in record["gates"].items():
        lines.append(f"- {name}: `{'PASS' if passed else 'BLOCKED'}`")
    lines.extend(["", "## 미완료 근거", ""])
    lines.extend(f"- {item}" for item in record["missingEvidence"])
    lines.extend(
        [
            "",
            "이 보고서의 `NOT_READY` 상태에서는 모델 ID를 운영 설정에 승격하지 않는다.",
            "실제 Staging 호출과 배포는 명시적 승인 후 별도 실행한다.",
            "",
        ]
    )
    return "\n".join(lines)
