#!/usr/bin/env python3
"""Generate evidence-gated model evaluation reports.

The reports deliberately keep measured Mock, Live, and Gold-gated results
separate. Missing evidence is rendered as ``null``/``N/A``; this script never
turns a Mock result or an unreviewed Gold case into a model score.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.model_selection import (  # noqa: E402
    analyze_model_selection,
    render_report,
)
from app.evaluation.tutor_gold import validate_tutor_gold  # noqa: E402
from app.model_comparison.catalog import MODEL_SPECS  # noqa: E402
from app.model_comparison.openrouter_catalog import (  # noqa: E402
    OpenRouterCatalogClient,
)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} must contain an object")
        rows.append(value)
    return rows


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    return value if isinstance(value, dict) else {}


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _repo_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(path)


def _counter(rows: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(row.get(key)) for row in rows))


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int((len(ordered) - 1) * percentile)))
    return round(ordered[index], 3)


def _catalog_summary(metadata: dict[str, Any]) -> dict[str, Any]:
    return {
        "modelId": metadata.get("model_id"),
        "name": metadata.get("name"),
        "available": metadata.get("available"),
        "reason": metadata.get("reason"),
        "contextWindow": metadata.get("context_window"),
        "inputPricePerMillion": metadata.get("input_price_per_million"),
        "outputPricePerMillion": metadata.get("output_price_per_million"),
        "supportedParameters": metadata.get("supported_parameters", []),
        "structuredOutputSupported": metadata.get("structured_output_supported"),
        "endpoints": metadata.get("endpoints", []),
        "providers": metadata.get("providers", []),
        "fetchedAt": metadata.get("fetched_at"),
    }


def _model_result(
    model_id: str,
    comparison_rows: list[dict[str, Any]],
    quality_rows: list[dict[str, Any]],
    catalog: dict[str, Any] | None,
) -> dict[str, Any]:
    comparisons = [row for row in comparison_rows if row.get("model_id") == model_id]
    quality = [row for row in quality_rows if row.get("modelId") == model_id]
    mock = [row for row in comparisons if row.get("mode") == "mock"]
    interim = [row for row in comparisons if row.get("mode") == "interim"]
    live = [
        row
        for row in comparisons
        if row.get("mode") in {"live", "final", "live_smoke"}
    ]
    live_success = [row for row in live if row.get("status") == "ok"]
    final_quality = [
        row
        for row in quality
        if row.get("evaluationStatus") in {"EVALUATED", "SCORED"}
        and row.get("evaluationStage", "FINAL_MODEL_EVALUATION")
        == "FINAL_MODEL_EVALUATION"
        and row.get("totalEducationScore") is not None
    ]
    preliminary_quality = [
        row
        for row in quality
        if row.get("evaluationStatus") == "SCORED_PRELIMINARY"
    ]
    gated_quality = [
        row
        for row in quality
        if row.get("evaluationStatus") == "NOT_EVALUATED_UNREVIEWED_GOLD"
    ]
    measured_errors = Counter(
        str(error.get("code"))
        for row in final_quality + preliminary_quality
        for error in row.get("criticalErrors", [])
        if isinstance(error, dict)
    )
    latencies = [
        float(row["latency_ms"])
        for row in live_success
        if isinstance(row.get("latency_ms"), (int, float))
    ]
    costs = [
        float(row["estimated_cost_usd"])
        for row in live_success
        if isinstance(row.get("estimated_cost_usd"), (int, float))
    ]
    actual_costs = [
        float(row["actual_cost_usd"])
        for row in live_success
        if isinstance(row.get("actual_cost_usd"), (int, float))
    ]
    ttft = [
        float(row["ttft_ms"])
        for row in live_success
        if isinstance(row.get("ttft_ms"), (int, float))
    ]
    timeout_count = 0
    for row in live:
        error = row.get("error")
        error_type = error.get("type", "") if isinstance(error, dict) else ""
        if (
            str(row.get("error_type", error_type)).casefold()
            in {"timeout", "generationtimeouterror"}
        ):
            timeout_count += 1
    return {
        "modelId": model_id,
        "catalog": catalog,
        "attempts": {
            "mock": len(mock),
            "interim": len(interim),
            "live": len(live),
            "liveSuccessful": len(live_success),
            "liveFailed": len(live) - len(live_success),
        },
        "quality": {
            "finalScored": len(final_quality),
            "preliminaryScored": len(preliminary_quality),
            "goldGateBlocked": len(gated_quality),
            "educationQualityScore": None,
            "criticalErrorsMeasured": dict(measured_errors),
        },
        "operations": {
            "averageLatencyMs": round(sum(latencies) / len(latencies), 3)
            if latencies
            else None,
            "p50LatencyMs": _percentile(latencies, 0.50),
            "p95LatencyMs": _percentile(latencies, 0.95),
            "ttftMs": _percentile(ttft, 0.50),
            "successRate": round(len(live_success) / len(live), 4)
            if live
            else None,
            "timeoutRate": round(timeout_count / len(live), 4) if live else None,
            "errorRate": round((len(live) - len(live_success)) / len(live), 4)
            if live
            else None,
            "averageActualCostUsd": round(sum(actual_costs) / len(actual_costs), 8)
            if actual_costs
            else None,
            "averageEstimatedCostUsd": round(sum(costs) / len(costs), 8)
            if costs
            else None,
            "actualCostMeasured": bool(actual_costs),
        },
        "scores": {
            "educationQuality60": None,
            "operationsEfficiency40": None,
            "total100": None,
            "rank": None,
        },
        "status": "BLOCKED_NOT_READY",
        "measuredLatencySamples": len(latencies),
    }


def _comparison_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Leren Tutor 모델 비교 결과",
        "",
        f"- 평가 상태: `{report['evaluationStatus']}`",
        f"- 생성 시각: `{report['generatedAt']}`",
        "- 교육 품질과 운영 효율 점수는 필수 증거가 없어 산출하지 않음",
        "- 실제 측정하지 않은 값은 `N/A`로 표시",
        "",
        "## 최종 비교표",
        "",
        "| 모델 | 교육 품질 /60 | 운영 효율 /40 | 총점 /100 | p95(ms) | "
        "평균 실제 비용(USD) | 중대 오류율 | 상태 |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in report["models"]:
        operations = item["operations"]
        quality = item["quality"]
        score = item["scores"]
        measured_rows = quality["finalScored"] + quality["preliminaryScored"]
        critical_count = sum(quality["criticalErrorsMeasured"].values())
        critical_rate = (
            round(critical_count / measured_rows, 4) if measured_rows else None
        )
        lines.append(
            f"| `{item['modelId']}` | {_display(score['educationQuality60'])} | "
            f"{_display(score['operationsEfficiency40'])} | "
            f"{_display(score['total100'])} | "
            f"{_display(operations['p95LatencyMs'])} | "
            f"{_display(operations['averageActualCostUsd'])} | "
            f"{_display(critical_rate)} | {item['status']} |"
        )
    lines.extend(
        [
            "",
            "## 모델 카탈로그 확인",
            "",
            "가격은 OpenRouter 카탈로그 조회 시점 기준 USD/1M tokens이며, "
            "실제 호출 비용과 다르다.",
            "",
            "| 모델 | 사용 가능 | 입력 가격 | 출력 가격 | Context | 구조화 출력 |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    for item in report["models"]:
        catalog = item["catalog"] or {}
        lines.append(
            f"| `{item['modelId']}` | {catalog.get('available', 'N/A')} | "
            f"{catalog.get('inputPricePerMillion', 'N/A')} | "
            f"{catalog.get('outputPricePerMillion', 'N/A')} | "
            f"{catalog.get('contextWindow', 'N/A')} | "
            f"{catalog.get('structuredOutputSupported', 'N/A')} |"
        )
    lines.extend(
        [
            "",
            "## 해석",
            "",
            "현재 100개 Gold 사례가 독립 승인되지 않았고 실제 Live 호출도 "
            "수행하지 않았으므로 모델 순위와 기본/Fallback 모델을 선정하지 않는다.",
            "Mock 결과는 하네스 동작 검증용이며 교육 품질 점수에 포함하지 않는다.",
            "",
        ]
    )
    return "\n".join(lines)


def _display(value: Any) -> str:
    return "N/A" if value is None else str(value)


def _error_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Leren Tutor 모델 오류 분석",
        "",
        f"- 평가 상태: `{report['evaluationStatus']}`",
        "- 미승인 Gold와 Mock 응답은 모델 오류율로 해석하지 않음",
        "",
        "## 측정 결과",
        "",
        "| 항목 | 결과 |",
        "|---|---|",
        "| 경제 개념 오류 | N/A — 승인 Gold 및 Live 답변 없음 |",
        "| 환각 사례 | N/A — 승인 근거 및 Live 답변 없음 |",
        "| 오개념 진단 오류 | N/A — 승인 Gold 및 점수 없음 |",
        "| 허위 Citation | N/A — 승인 근거 및 Live 답변 없음 |",
        "| 검색 근거 오류 | N/A — 현재 Mock은 승인 근거 부재로 `no_evidence` 처리 |",
        "",
        "## Gold 게이트 차단",
        "",
        f"- 전체 평가 사례: {report['dataset']['count']}건",
        f"- 독립 승인 사례: {report['dataset']['independentApproved']}건",
        f"- Gold 게이트 차단 품질 결과: {report['qualityGateBlocked']}건",
        "- 위 차단은 후보 모델의 품질 오류가 아니라 평가 입력 승인 부족이다.",
        "",
    ]
    return "\n".join(lines)


def _status_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Leren Tutor 모델 평가 진행 현황",
        "",
        f"- 전체 상태: `{report['evaluationStatus']}`",
        f"- 생성 시각: `{report['generatedAt']}`",
        "",
        "| 단계 | 상태 | 실제 결과 | 차단 사유 |",
        "|---|---|---|---|",
        "| Gold 검증 | BLOCKED | 100건, 독립 승인 0건 | "
        "conceptCode·근거·라이선스·검수 이력 부족 |",
        "| Mock 비교 | COMPLETED | 5개 모델 하네스 실행 | 교육 품질 점수 대상 아님 |",
        "| Live Smoke | BLOCKED | 실제 채팅 호출 0건 | 비용 상한·실행 승인 없음 |",
        "| Interim 비교 | BLOCKED | 실제 비교 0건 | 승인된 사례 0건 |",
        "| Final 비교 | BLOCKED | 실제 비교 0건 | 전체 Gold 승인 및 Live 결과 없음 |",
        "| 사람 평가 | BLOCKED | 완료된 독립 사람 평가 없음 | "
        "승인 Gold 및 검수 증거 부족 |",
        "| Context A/B/C | BLOCKED | 별도 현재 결과 파일 없음 | "
        "승인 Gold·Live 결과 없음 |",
        "",
        "## 다음 필수 조건",
        "",
        "1. 100개 사례의 canonical conceptCode 매핑",
        "2. 출처 승인과 라이선스 승인 분리 확인",
        "3. 두 명 이상의 독립 검수와 adjudication 기록",
        "4. 비용 상한을 명시한 `--execute` 승인",
        "5. 5개 모델 동일 조건 Live 비교 및 사람 평가",
        "",
    ]
    return "\n".join(lines)


async def _fetch_catalog() -> dict[str, dict[str, Any]]:
    metadata = await OpenRouterCatalogClient().fetch(
        [spec.model_id for spec in MODEL_SPECS]
    )
    return {
        model_id: _catalog_summary(item.as_dict())
        for model_id, item in metadata.items()
    }


def build_parser() -> argparse.ArgumentParser:
    evaluation = ROOT / "data" / "evaluation"
    reports = ROOT / "reports"
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dataset", type=Path, default=evaluation / "tutor_test_100.jsonl"
    )
    parser.add_argument(
        "--comparison", type=Path, default=evaluation / "tutor_model_results.jsonl"
    )
    parser.add_argument(
        "--quality", type=Path, default=evaluation / "tutor_quality_results.jsonl"
    )
    parser.add_argument(
        "--human-review",
        type=Path,
        default=evaluation / "tutor_human_review_anonymous.jsonl",
    )
    parser.add_argument(
        "--context", type=Path, default=evaluation / "tutor_context_abc_results.jsonl"
    )
    parser.add_argument(
        "--gold-validation",
        type=Path,
        default=reports / "evaluation" / "tutor_gold_validation.json",
    )
    parser.add_argument(
        "--final-json",
        type=Path,
        default=reports / "model_comparison" / "final_comparison.json",
    )
    parser.add_argument(
        "--final-report",
        type=Path,
        default=reports / "model_comparison" / "final_comparison.md",
    )
    parser.add_argument(
        "--error-report",
        type=Path,
        default=reports / "model_comparison" / "error_analysis.md",
    )
    parser.add_argument(
        "--status-report",
        type=Path,
        default=reports / "model_comparison" / "evaluation_status.md",
    )
    parser.add_argument(
        "--selection-record",
        type=Path,
        default=reports / "model_selection_record.json",
    )
    parser.add_argument(
        "--selection-report",
        type=Path,
        default=reports / "model_selection_report.md",
    )
    parser.add_argument("--no-catalog-refresh", action="store_true")
    return parser


def run(args: argparse.Namespace) -> dict[str, Any]:
    dataset = _read_jsonl(args.dataset)
    comparison = _read_jsonl(args.comparison)
    quality = _read_jsonl(args.quality)
    human_review = _read_jsonl(args.human_review)
    context = _read_jsonl(args.context)
    validation, _ = validate_tutor_gold(dataset)
    validation_snapshot = _read_json(args.gold_validation) or validation
    catalog: dict[str, dict[str, Any]] = {}
    if not args.no_catalog_refresh:
        try:
            catalog = asyncio.run(_fetch_catalog())
        except Exception as exc:  # pragma: no cover - network-dependent
            catalog = {"_error": {"type": type(exc).__name__}}
    model_rows = [
        _model_result(
            spec.model_id,
            comparison,
            quality,
            catalog.get(spec.model_id),
        )
        for spec in MODEL_SPECS
    ]
    independent_approved = sum(
        row.get("goldStatus") == "INDEPENDENT_APPROVED" for row in dataset
    )
    quality_gate_blocked = sum(
        row.get("evaluationStatus") == "NOT_EVALUATED_UNREVIEWED_GOLD"
        for row in quality
    )
    generated_at = datetime.now(timezone.utc).isoformat()
    report = {
        "schemaVersion": 1,
        "generatedAt": generated_at,
        "evaluationStatus": "NOT_READY",
        "dataset": {
            "path": _repo_path(args.dataset),
            "count": len(dataset),
            "independentApproved": independent_approved,
            "goldStatusCounts": _counter(dataset, "goldStatus"),
            "validation": {
                "readyForScoring": validation_snapshot["readyForScoring"],
                "blockingFindingCount": validation_snapshot[
                    "blockingFindingCount"
                ],
                "curationInputs": validation_snapshot.get("curationInputs"),
            },
        },
        "models": model_rows,
        "qualityGateBlocked": quality_gate_blocked,
        "inputCounts": {
            "comparison": len(comparison),
            "quality": len(quality),
            "humanReview": len(human_review),
            "contextABC": len(context),
        },
        "ranking": [],
        "selection": {
            "primaryModel": None,
            "fallbackModel": None,
            "reason": "required Gold, Live, and independent human evidence is missing",
        },
        "catalogFetch": catalog.get("_error") or "COMPLETED",
    }
    _write_json(args.final_json, report)
    _write_text(args.final_report, _comparison_markdown(report))
    _write_text(args.error_report, _error_markdown(report))
    _write_text(args.status_report, _status_markdown(report))

    selection_record = analyze_model_selection(
        comparison_rows=comparison,
        quality_rows=quality,
        dataset_rows=dataset,
        human_review_rows=human_review,
        context_rows=context,
    )
    _write_json(args.selection_record, selection_record)
    _write_text(args.selection_report, render_report(selection_record))
    return report


def main() -> int:
    report = run(build_parser().parse_args())
    print(
        json.dumps(
            {
                "evaluationStatus": report["evaluationStatus"],
                "datasetCount": report["dataset"]["count"],
                "independentApproved": report["dataset"]["independentApproved"],
                "rankingCount": len(report["ranking"]),
                "finalReport": "reports/model_comparison/final_comparison.md",
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
