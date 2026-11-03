# ruff: noqa: E501

"""Run the KDI/BOK 320-document classification experiment.

The default command never calls an external model and reuses stored LLM pilot
results for diagnostic overlap. ``--execute-llm`` explicitly runs a
KDI/BOK-balanced pilot capped at 20 requests. Independent Gold metrics remain
blocked until the Gold Review workflow produces an approved,
provenance-checked test set.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dataset_pipeline.evaluation import (  # noqa: E402
    confusion_matrix,
    positive_for_use,
    precision_recall_f1,
)
from app.dataset_pipeline.evaluation_dataset import (  # noqa: E402
    build_combined_dataset,
    label_agreement_report,
)
from app.dataset_pipeline.keywords import (  # noqa: E402
    Chapter,
    classify_chunk_by_keywords,
)
from app.dataset_pipeline.tokenizer import ExactTokenizer  # noqa: E402
from scripts._pipeline_support import load_yaml  # noqa: E402
from scripts.compare_precision_methods import _load_llm_results  # noqa: E402
from scripts.precision_llm_pilot import run as run_llm_pilot  # noqa: E402
from scripts.rebuild_precision_pipeline import _make_chunk  # noqa: E402

DEFAULT_OUTPUT_DIR = ROOT / "reports" / "evaluation"
DEFAULT_COMBINED = ROOT / "data" / "processed" / "evaluation" / "combined_320.jsonl"
DEFAULT_PILOT = ROOT / "data" / "labeled" / "precision" / "llm_pilot_results.jsonl"
DEFAULT_GOLD = ROOT / "reports" / "independent_gold_test.csv"
TOKENIZER_NAME = "gpt-4o-mini"
LLM_THRESHOLD = 0.70
RANDOM_SEED = 20261029


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def write_csv(
    path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_chapter(path: Path) -> Chapter:
    payload = load_yaml(path)
    chapters = payload.get("chapters", [])
    if not chapters:
        raise ValueError(f"{path} contains no chapter")
    return Chapter.from_dict(chapters[0])


def _record_for_prediction(row: dict[str, Any], content: str) -> dict[str, Any]:
    result = dict(row)
    result["content"] = content or row["content"]
    result["source_group"] = row["source"]
    result["quality"] = row["data_quality_status"]
    return result


def run_keyword_predictions(
    rows: list[dict[str, Any]], chapter: Chapter, tokenizer: ExactTokenizer
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        content = (
            row["source_content"]
            if row["source_match_type"] != "SOURCE_NOT_FOUND"
            else row["content"]
        )
        result = classify_chunk_by_keywords(
            _make_chunk(_record_for_prediction(row, content), tokenizer), chapter
        )
        output.append(
            {
                "source": row["source"],
                "document_id": row["document_id"],
                "title": row["title"],
                "source_match_type": row["source_match_type"],
                "content_hash": row["content_hash"],
                "keyword_strategy": result["keyword_strategy"],
                "keyword_candidate": bool(result["candidate"]),
                "keyword_match_score": result["keyword_match_score"],
                "keyword_score_is_not_relevance": True,
                "matched_keywords": result["matched_keywords"],
                "matched_keyword_types": result["matched_keyword_types"],
                "exclude_keyword_matches": result["exclude_keyword_matches"],
                "evidence_span": result["evidence_span"] or "",
                "reference_label": row["proposed_final_label"],
                "reference_label_provenance": row["label_provenance"],
                "review_status": "PENDING",
            }
        )
    return output


def _ternary_label(score: float | None) -> int | None:
    """Diagnostic quantization of the LLM continuous score, not a Gold label."""
    if score is None or not math.isfinite(score):
        return None
    if score < 1 / 3:
        return 0
    if score < 2 / 3:
        return 1
    return 2


def _pilot_row(
    results: dict[str, dict[str, Any]], document_id: str
) -> dict[str, Any] | None:
    row = results.get(document_id)
    if not row:
        return None
    raw_score = row.get("relevance_score")
    numeric_score = (
        float(raw_score)
        if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool)
        else None
    )
    return {
        "relevance_score": numeric_score,
        "predicted_label": _ternary_label(numeric_score),
        "reason": row.get("reason", ""),
        "evidence_quote": row.get("evidence_span", ""),
        "model": row.get("provider_response_model") or row.get("model_name", ""),
        "prompt_version": row.get("prompt_version", ""),
        "rubric_version": row.get("rubric_version", ""),
        "latency_ms": round(float(row["latency_seconds"]) * 1000, 2)
        if row.get("latency_seconds") is not None
        else None,
        "input_tokens": row.get("input_tokens_actual")
        or row.get("input_tokens_estimated"),
        "output_tokens": row.get("output_tokens_actual")
        or row.get("output_tokens_estimated"),
        "status": row.get("status", "UNKNOWN"),
        "review_status": row.get("review_status", "PENDING"),
        "evidence_span_valid": row.get("evidence_span_valid"),
        "execution_mode": row.get("execution_mode", "STORED_PILOT"),
        "json_parse_failed": bool(row.get("json_parse_failed", False)),
    }


def run_llm_predictions(
    rows: list[dict[str, Any]], pilot_results: dict[str, dict[str, Any]]
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        pilot = _pilot_row(pilot_results, row["document_id"])
        base = {
            "source": row["source"],
            "document_id": row["document_id"],
            "title": row["title"],
            "content_hash": row["content_hash"],
            "reference_label": row["proposed_final_label"],
            "reference_label_provenance": row["label_provenance"],
            "model": pilot["model"] if pilot else "",
            "prompt_version": pilot["prompt_version"] if pilot else "",
            "rubric_version": pilot["rubric_version"] if pilot else "",
            "latency_ms": pilot["latency_ms"] if pilot else None,
            "input_tokens": pilot["input_tokens"] if pilot else None,
            "output_tokens": pilot["output_tokens"] if pilot else None,
            "llm_status": pilot["status"] if pilot else "NOT_EXECUTED",
            "relevance_score": pilot["relevance_score"] if pilot else None,
            "predicted_label": pilot["predicted_label"] if pilot else None,
            "reason": pilot["reason"] if pilot else "",
            "evidence_quote": pilot["evidence_quote"] if pilot else "",
            "evidence_span_valid": pilot["evidence_span_valid"] if pilot else None,
            "json_parse_failed": pilot["json_parse_failed"] if pilot else None,
            "review_status": pilot["review_status"] if pilot else "NOT_EXECUTED",
            "prediction_status": (
                "LLM_EXECUTED_PENDING"
                if pilot and pilot.get("execution_mode") == "API_EXECUTED"
                else "PILOT_REUSED_PENDING"
                if pilot
                else "NOT_EXECUTED"
            ),
        }
        output.append(base)
    return output


def run_hybrid_predictions(
    rows: list[dict[str, Any]],
    keyword_rows: list[dict[str, Any]],
    llm_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    by_id = {item["document_id"]: item for item in llm_rows}
    output: list[dict[str, Any]] = []
    for keyword in keyword_rows:
        llm = by_id[keyword["document_id"]]
        candidate = keyword["keyword_candidate"]
        if not candidate:
            status = "COMPLETED_KEYWORD_NEGATIVE"
            predicted_label = 0
            score = None
        elif llm["prediction_status"] in {
            "PILOT_REUSED_PENDING",
            "LLM_EXECUTED_PENDING",
        }:
            status = "LLM_OBSERVED_PENDING_REVIEW"
            predicted_label = llm["predicted_label"]
            score = llm["relevance_score"]
        else:
            status = "NOT_EXECUTED_LLM_MISSING"
            predicted_label = None
            score = None
        output.append(
            {
                "source": keyword["source"],
                "document_id": keyword["document_id"],
                "title": keyword["title"],
                "content_hash": keyword["content_hash"],
                "keyword_candidate": candidate,
                "matched_keywords": keyword["matched_keywords"],
                "llm_relevance_score": score,
                "predicted_label": predicted_label,
                "question_generation_positive": predicted_label == 2
                if predicted_label is not None
                else None,
                "tutor_retrieval_positive": predicted_label in {1, 2}
                if predicted_label is not None
                else None,
                "reference_label": keyword["reference_label"],
                "reference_label_provenance": keyword["reference_label_provenance"],
                "prediction_status": status,
                "review_status": "PENDING",
            }
        )
    return output


def _proxy_metrics(
    predictions: dict[str, bool], rows: list[dict[str, Any]], usage: str
) -> dict[str, Any]:
    reference = {
        row["document_id"]: row["proposed_final_label"]
        for row in rows
        if row["proposed_final_label"] in {0, 1, 2}
    }
    common = sorted(set(reference) & set(predictions))
    if not common:
        return {
            "status": "NOT_EVALUATED_NO_REFERENCE_LABEL",
            "population_count": 0,
            "metrics": None,
            "matrix": None,
        }
    actual = [positive_for_use(reference[document_id], usage) for document_id in common]
    predicted = [predictions[document_id] for document_id in common]
    matrix = confusion_matrix(predicted, actual)
    return {
        "status": "DRY_RUN_AI_REFERENCE",
        "population_count": len(common),
        "metrics": precision_recall_f1(matrix),
        "matrix": matrix,
        "reference_label_provenance_counts": dict(
            Counter(
                rows_by_id(rows, common)[document_id]["label_provenance"]
                for document_id in common
            )
        ),
        "interpretation": "Proxy agreement against workbook labels/AB consensus; not independent Gold performance.",
    }


def rows_by_id(
    rows: list[dict[str, Any]], ids: Iterable[str] | None = None
) -> dict[str, dict[str, Any]]:
    values = {row["document_id"]: row for row in rows}
    return values if ids is None else {key: values[key] for key in ids if key in values}


def _method_predictions(
    rows: list[dict[str, Any]],
    keyword_rows: list[dict[str, Any]],
    llm_rows: list[dict[str, Any]],
    hybrid_rows: list[dict[str, Any]],
    llm_execution_status: str = "REUSED_EXISTING_LLM_PILOT",
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    source_by_id = rows_by_id(rows)
    keyword_map = {row["document_id"]: row["keyword_candidate"] for row in keyword_rows}
    llm_map = {
        row["document_id"]: row["relevance_score"] >= LLM_THRESHOLD
        for row in llm_rows
        if row["relevance_score"] is not None
    }
    hybrid_map = {
        row["document_id"]: bool(row["tutor_retrieval_positive"])
        for row in hybrid_rows
        if row["tutor_retrieval_positive"] is not None
    }
    hybrid_status_counts = Counter(row["prediction_status"] for row in hybrid_rows)
    keyword_candidate_count = sum(keyword_map.values())
    candidate_observed_count = hybrid_status_counts.get(
        "LLM_OBSERVED_PENDING_REVIEW", 0
    )
    candidate_missing_count = hybrid_status_counts.get("NOT_EXECUTED_LLM_MISSING", 0)
    methods = {
        "keyword_only": {
            "status": "EXECUTED_OFFLINE",
            "coverage_count": len(keyword_map),
            "population_count": len(rows),
            "binary_policy": "candidate=true for both diagnostic policies",
            "question_generation": _proxy_metrics(
                keyword_map, rows, "question_generation"
            ),
            "tutor_retrieval": _proxy_metrics(keyword_map, rows, "tutor_retrieval"),
        },
        "llm_only": {
            "status": (
                "EXECUTED_LLM_PILOT"
                if llm_execution_status
                in {"EXECUTED_LLM_PILOT", "REUSED_EXECUTED_LLM_PILOT"}
                else "DRY_RUN_INCOMPLETE_PILOT"
            ),
            "coverage_count": len(llm_map),
            "population_count": len(rows),
            "threshold": LLM_THRESHOLD,
            "question_generation": _proxy_metrics(llm_map, rows, "question_generation"),
            "tutor_retrieval": _proxy_metrics(llm_map, rows, "tutor_retrieval"),
        },
        "hybrid": {
            "status": (
                "EXECUTED_LLM_PILOT"
                if llm_execution_status
                in {"EXECUTED_LLM_PILOT", "REUSED_EXECUTED_LLM_PILOT"}
                else "DRY_RUN_INCOMPLETE_PILOT"
            ),
            "coverage_count": len(hybrid_map),
            "population_count": len(rows),
            "rule": "Keyword candidates go to LLM; non-candidates remain explicit negative; missing candidate LLM results remain pending.",
            "keyword_negative_docs": hybrid_status_counts.get(
                "COMPLETED_KEYWORD_NEGATIVE", 0
            ),
            "keyword_candidate_docs": keyword_candidate_count,
            "candidate_llm_observed_docs": candidate_observed_count,
            "candidate_llm_not_observed_docs": candidate_missing_count,
            "pending_docs": candidate_missing_count,
            "question_generation": _proxy_metrics(
                {key: value for key, value in hybrid_map.items()},
                rows,
                "question_generation",
            ),
            "tutor_retrieval": _proxy_metrics(hybrid_map, rows, "tutor_retrieval"),
        },
    }
    overlap = []
    for document_id in sorted(set(keyword_map) & set(llm_map)):
        row = source_by_id[document_id]
        overlap.append(
            {
                "source": row["source"],
                "document_id": document_id,
                "title": row["title"],
                "keyword_candidate": keyword_map[document_id],
                "llm_positive_at_threshold": llm_map[document_id],
                "hybrid_positive_at_threshold": hybrid_map.get(document_id),
                "llm_predicted_label": next(
                    item["predicted_label"]
                    for item in llm_rows
                    if item["document_id"] == document_id
                ),
                "reference_label": row["proposed_final_label"],
                "reference_label_provenance": row["label_provenance"],
                "comparison_status": "REFERENCE_DISAGREEMENT_ONLY"
                if row["proposed_final_label"] is not None
                else "NO_REFERENCE_LABEL",
            }
        )
    methods["pairwise_overlap"] = {
        "keyword_llm_count": len(overlap),
        "keyword_llm_agreement": sum(
            item["keyword_candidate"] == item["llm_positive_at_threshold"]
            for item in overlap
        )
        / len(overlap)
        if overlap
        else None,
        "keyword_hybrid_count": sum(
            item["hybrid_positive_at_threshold"] is not None for item in overlap
        ),
        "llm_hybrid_agreement": (
            sum(
                item["llm_positive_at_threshold"]
                == item["hybrid_positive_at_threshold"]
                for item in overlap
                if item["hybrid_positive_at_threshold"] is not None
            )
            / sum(item["hybrid_positive_at_threshold"] is not None for item in overlap)
            if any(item["hybrid_positive_at_threshold"] is not None for item in overlap)
            else None
        ),
    }
    return methods, overlap


def _error_rows(
    rows: list[dict[str, Any]], keyword_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    source = rows_by_id(rows)
    for prediction in keyword_rows:
        row = source[prediction["document_id"]]
        label = row["proposed_final_label"]
        if label is None:
            continue
        case = ""
        if prediction["keyword_candidate"] and label == 0:
            case = "KEYWORD_FALSE_POSITIVE_REFERENCE"
        elif not prediction["keyword_candidate"] and label == 2:
            case = "KEYWORD_FALSE_NEGATIVE_REFERENCE"
        if not case:
            continue
        result.append(
            {
                "case": case,
                "source": row["source"],
                "document_id": row["document_id"],
                "title": row["title"],
                "content_excerpt": row["content"][:500],
                "keyword_candidate": prediction["keyword_candidate"],
                "matched_keywords": prediction["matched_keywords"],
                "reference_label": label,
                "reference_label_provenance": row["label_provenance"],
                "review_status": "PENDING_HUMAN_REVIEW",
            }
        )
    return result


def _write_plot_files(
    output_dir: Path,
    rows: list[dict[str, Any]],
    keyword_rows: list[dict[str, Any]],
    llm_rows: list[dict[str, Any]],
    hybrid_rows: list[dict[str, Any]],
    methods: dict[str, Any],
) -> dict[str, str]:
    try:
        import matplotlib as mpl
        import matplotlib.pyplot as plt
    except ImportError:
        return {"status": "PLOT_DEPENDENCY_MISSING"}
    mpl.rcParams["font.family"] = "Apple SD Gothic Neo"
    mpl.rcParams["axes.unicode_minus"] = False
    output_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, str] = {}

    counts = Counter(row["source"] for row in rows)
    fig, axis = plt.subplots(figsize=(5, 4))
    axis.bar(list(counts), list(counts.values()), color=["#3762A8", "#D98C2B"])
    axis.set_title("문서 수")
    axis.set_ylabel("건수")
    fig.tight_layout()
    path = output_dir / "dataset_counts.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths["dataset_counts"] = display_path(path)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4), sharey=True)
    for axis, label_key, title in zip(
        axes, ("label_a", "label_b"), ("관련도 A", "관련도 B")
    ):
        for index, source in enumerate(("KDI", "BOK")):
            source_rows = [
                row
                for row in rows
                if row["source"] == source and row[label_key] is not None
            ]
            counts = Counter(row[label_key] for row in source_rows)
            axis.bar(
                [str(value) for value in range(3)],
                [counts[value] for value in range(3)],
                alpha=0.65,
                label=source,
                width=0.4,
                align="edge" if index == 0 else "center",
            )
        axis.set_title(title)
        axis.set_xlabel("점수")
        axis.legend()
    axes[0].set_ylabel("건수")
    fig.tight_layout()
    path = output_dir / "label_distributions.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths["label_distributions"] = display_path(path)

    comparable = [
        row for row in rows if row["label_a"] is not None and row["label_b"] is not None
    ]
    matrix = [
        [
            sum(
                row["label_a"] == actual and row["label_b"] == predicted
                for row in comparable
            )
            for predicted in range(3)
        ]
        for actual in range(3)
    ]
    fig, axis = plt.subplots(figsize=(5, 4))
    image = axis.imshow(matrix, cmap="Blues")
    for actual in range(3):
        for predicted in range(3):
            axis.text(
                predicted, actual, matrix[actual][predicted], ha="center", va="center"
            )
    axis.set_xlabel("관련도 B")
    axis.set_ylabel("관련도 A")
    axis.set_title("A/B 교차표")
    fig.colorbar(image, ax=axis, fraction=0.046, pad=0.04)
    fig.tight_layout()
    path = output_dir / "label_confusion_matrix.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths["label_confusion_matrix"] = display_path(path)

    agreement_rates = []
    agreement_labels = []
    for source in ("KDI", "BOK"):
        source_rows = [row for row in rows if row["source"] == source]
        pairs = [
            row
            for row in source_rows
            if row["label_a"] is not None and row["label_b"] is not None
        ]
        agreement_labels.append(source)
        agreement_rates.append(
            sum(row["label_a"] == row["label_b"] for row in pairs) / len(pairs)
            if pairs
            else 0
        )
    fig, axis = plt.subplots(figsize=(5, 4))
    axis.bar(agreement_labels, agreement_rates, color=["#3762A8", "#D98C2B"])
    axis.set_ylim(0, 1)
    axis.set_title("기관별 A/B 일치율")
    axis.set_ylabel("일치율")
    fig.tight_layout()
    path = output_dir / "label_agreement.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths["label_agreement"] = display_path(path)

    method_counts = {
        "Keyword candidate": sum(row["keyword_candidate"] for row in keyword_rows),
        "LLM pilot score≥0.7": sum(
            (row["relevance_score"] or 0) >= LLM_THRESHOLD for row in llm_rows
        ),
        "Hybrid resolved": sum(
            row["prediction_status"] != "NOT_EXECUTED_LLM_MISSING"
            for row in hybrid_rows
        ),
    }
    fig, axis = plt.subplots(figsize=(7, 4))
    axis.bar(
        list(method_counts),
        list(method_counts.values()),
        color=["#3762A8", "#5FAF8B", "#D98C2B"],
    )
    axis.set_title("분류 방식별 관측 판정 수(파일럿 포함)")
    axis.set_ylabel("건수")
    axis.tick_params(axis="x", rotation=15)
    fig.tight_layout()
    path = output_dir / "method_distributions.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths["method_distributions"] = display_path(path)

    agreement_values = [
        methods["pairwise_overlap"].get("keyword_llm_agreement") or 0,
        methods["pairwise_overlap"].get("llm_hybrid_agreement") or 0,
    ]
    fig, axis = plt.subplots(figsize=(6, 4))
    axis.bar(["Keyword–LLM", "LLM–Hybrid"], agreement_values, color="#7C5CBF")
    axis.set_ylim(0, 1)
    axis.set_title("파일럿 겹침 구간 일치율")
    axis.set_ylabel("일치율")
    fig.tight_layout()
    path = output_dir / "method_agreement.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths["method_agreement"] = display_path(path)

    latencies = [row["latency_ms"] for row in llm_rows if row["latency_ms"] is not None]
    tokens = [
        sum(value or 0 for value in (row["input_tokens"], row["output_tokens"]))
        for row in llm_rows
    ]
    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    axes[0].bar(
        ["평균", "P95"],
        [
            statistics.mean(latencies),
            sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)],
        ],
        color="#C45A65",
    ) if latencies else None
    axes[0].set_title("LLM 지연시간(ms)")
    axes[0].set_ylabel("ms")
    axes[1].bar(
        ["평균 토큰"], [statistics.mean(tokens) if tokens else 0], color="#5B8E9F"
    )
    axes[1].set_title("LLM 파일럿 토큰")
    fig.tight_layout()
    path = output_dir / "api_usage_latency.png"
    fig.savefig(path, dpi=160)
    plt.close(fig)
    paths["api_usage_latency"] = display_path(path)
    return paths


def _report_markdown(
    summary: dict[str, Any],
    agreement: dict[str, Any],
    methods: dict[str, Any],
    errors: list[dict[str, Any]],
    plot_paths: dict[str, str],
    keyword_count: int,
    llm_count: int,
    api_execution: dict[str, Any] | None = None,
) -> str:
    api_execution = api_execution or {}
    api_calls = int(api_execution.get("llm_calls", 0))
    recorded_api_calls = int(api_execution.get("recorded_api_calls", api_calls))
    llm_status = api_execution.get("status", "NOT_EXECUTED")
    source_counts = summary["source_row_counts"]
    lines = [
        "# Leren KDI/BOK Classification Evaluation Report",
        "",
        "## 1. 연구 개요",
        "",
        "물가와 인플레이션 챕터의 문서 선별을 위해 기존 데이터 파이프라인에 KDI·BOK 라벨링 표본을 연결하고 Keyword-only, LLM-only, Hybrid의 재현 가능한 비교 실행 경로를 검증했다.",
        "문제 생성은 관련도 2를, Tutor 후보 선별은 관련도 1·2를 양성으로 보는 별도 정책을 사용한다.",
        "",
        "## 2. 데이터셋 및 파일 감사",
        "",
        f"- KDI: {source_counts.get('KDI', 0)}건; BOK: {source_counts.get('BOK', 0)}건; 통합: {summary['combined_row_count']}건",
        f"- canonical corpus: {summary['corpus_inventory']['document_count']}건 ({summary['corpus_inventory']['document_count_by_source']})",
        f"- dataset_version: `{summary['dataset_version']}`",
        f"- 중복 document_id: {len(summary['duplicate_document_ids'])}건; 잘못된 ID: {len(summary['invalid_document_ids'])}건",
        "- Excel 원본은 읽기 전용으로 처리했고, `확정 골드=완료`는 숫자 Gold로 변환하지 않았다.",
        "",
        "## 3. 원본 대조 및 라벨 검증",
        "",
        "원문 대조 상태는 EXACT_MATCH, NORMALIZED_MATCH, CONTENT_MISMATCH, SOURCE_NOT_FOUND로 기록했다. 불일치 원문은 자동 수정하지 않았다.",
        "",
        "| 기관 | A/B 비교 | 일치 | 불일치 | 일치율 | Cohen kappa |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for source in ("KDI", "BOK", "ALL"):
        item = agreement["by_source"][source]
        kappa = "null" if item["cohen_kappa"] is None else f"{item['cohen_kappa']:.4f}"
        rate = (
            "null"
            if item["agreement_rate"] is None
            else f"{item['agreement_rate']:.4f}"
        )
        lines.append(
            f"| {source} | {item['comparable_count']} | {item['agree_count']} | {item['disagree_count']} | {rate} | {kappa} |"
        )
    lines.extend(
        [
            "",
            "A/B 결과의 해석은 `AI_REVIEW_AGREEMENT`로 제한한다. 검수자 신원·독립성 이력이 없으므로 `HUMAN_INTER_RATER_AGREEMENT`로 보고하지 않았다.",
            "BOK의 A/B 불일치와 `B 재검토 대상=Y`는 별도 필드이며 동일한 개념으로 합산하지 않았다.",
            "",
            "## 4. 실험 방법",
            "",
            "- Keyword-only: 기존 `classify_chunk_by_keywords`의 제목+본문 검색과 가중 후보 점수를 사용한다. 점수는 관련도 확률이 아니며 후보 신호다.",
            f"- LLM-only: {llm_status}; 관측 결과만 사용하며 신규 API 호출은 {api_calls}건이다. 미실행 문서는 빈 예측으로 남겼다.",
            "- Hybrid: Keyword 후보만 LLM 입력 대상으로 삼고, 비후보는 명시적 음성으로 남긴다. 후보인데 LLM 결과가 없으면 보류한다.",
            "",
            "## 5. 결과 및 평가 상태",
            "",
            f"- Keyword: 320건 전체 실행, 후보 {keyword_count}건",
            f"- LLM: 관측 {llm_count}건, 신규 호출 {api_calls}건",
            "- Hybrid: 파일럿·비후보를 합친 관측 결과만 저장; 전체 후보가 채워지지 않아 최종 평가 불가",
            "- 독립 Gold: 0건, 상태 `NOT_READY`; 따라서 최종 Precision/Recall/F1은 산출하지 않았다.",
            "- 아래 proxy 지표는 Excel 명시 라벨 또는 A/B 합의 proxy와의 일치도이며 독립 Gold 성능이 아니다.",
            "",
            "| 방법 | 상태 | 전체 모집단 | 예측/관측 수 |",
            "|---|---|---:|---:|",
        ]
    )
    for method in ("keyword_only", "llm_only", "hybrid"):
        item = methods[method]
        lines.append(
            f"| {method} | {item['status']} | {item['population_count']} | {item['coverage_count']} |"
        )
    lines.extend(
        [
            "",
            "## 6. 오분류가 아닌 판정 불일치 분석",
            "",
            f"Keyword 후보와 reference label이 충돌하는 사례는 {len(errors)}건이며, 독립 Gold가 없으므로 모두 `PENDING_HUMAN_REVIEW`로 기록했다.",
            "대표 유형은 Keyword false positive(키워드가 있으나 reference 0)와 Keyword false negative(키워드가 없으나 reference 2)이다.",
            "",
            "## 7. 한계 및 후속 작업",
            "",
            "1. 기존 320건 라벨은 개발·예비 분석 자료이며 독립 Gold가 아니다.",
            f"2. LLM 파일럿은 {llm_count}건이고 신규 호출 {api_calls}건(기록된 API 호출 {recorded_api_calls}건) 범위만 반영한다. 가격 설정이 없어 비용은 확인하지 않았다.",
            "3. KDI/BOK의 원문 표현과 출처 메타데이터가 다르므로 기관별 결과를 전체 성능으로 일반화하지 않는다.",
            "4. Gold Review에서 독립 검수와 합의가 끝난 test set이 준비되면 기존 `compare_precision_methods.py`에 연결해 P/R/F1과 FP/FN 그래프를 생성한다.",
            "",
            "## 8. 산출물",
            "",
        ]
    )
    for key, path in plot_paths.items():
        lines.append(f"- `{key}`: `{path}`")
    return "\n".join(lines) + "\n"


def _precision_eda_summary(
    summary: dict[str, Any],
    agreement: dict[str, Any],
    methods: dict[str, Any],
    rows: list[dict[str, Any]],
    keyword_rows: list[dict[str, Any]],
    llm_rows: list[dict[str, Any]],
    hybrid_rows: list[dict[str, Any]],
    plot_paths: dict[str, str],
    errors: list[dict[str, Any]],
    api_execution: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create the notebook-facing summary without inventing Gold metrics."""
    api_execution = api_execution or {}
    label_distributions: dict[str, dict[str, dict[str, int]]] = {}
    for source in ("KDI", "BOK", "ALL"):
        source_rows = rows if source == "ALL" else [row for row in rows if row["source"] == source]
        label_distributions[source] = {}
        for label_key in ("label_a", "label_b"):
            counts = Counter(
                str(row[label_key])
                for row in source_rows
                if row[label_key] in {0, 1, 2}
            )
            label_distributions[source][label_key] = {
                str(score): counts.get(str(score), 0) for score in range(3)
            }

    source_quality: dict[str, Any] = {}
    for source, report in summary["source_reports"].items():
        integrity = report["validation"]["integrity"]
        source_quality[source] = {
            "missing_document_id": len(report["validation"].get("missing_ids", [])),
            "missing_title": integrity["empty_title_count"],
            "empty_content": integrity["empty_content_count"],
            "duplicate_document_id": len(integrity["duplicate_ids"]),
            "duplicate_content": len(integrity["duplicate_contents"]),
            "source_locator_missing": integrity["missing_source_locator_count"],
            "quality_distribution": integrity["quality_distribution"],
            "original_quality_flag_count": integrity["original_quality_flag_count"],
            "content_hash_duplicate_rows": sum(integrity["duplicate_contents"].values()),
            "reconciliation_counts": report["reconciliation_counts"],
            "explicit_gold_numeric_count": report["explicit_gold_numeric_count"],
            "explicit_gold_nonnumeric_values": report["explicit_gold_nonnumeric_values"],
        }

    llm_observed = [row for row in llm_rows if row["prediction_status"] != "NOT_EXECUTED"]
    latencies = [row["latency_ms"] for row in llm_observed if row["latency_ms"] is not None]
    parse_failures = sum(row.get("json_parse_failed") is True for row in llm_observed)
    evidence_failures = sum(row["evidence_span_valid"] is False for row in llm_observed)

    b_review_rows = [row for row in rows if row["b_review"] == "Y"]
    b_review_disagreements = sum(
        row["label_a"] is not None
        and row["label_b"] is not None
        and row["label_a"] != row["label_b"]
        for row in b_review_rows
    )
    b_review_by_source = {}
    b_review_disagreement_by_source = {}
    for source in ("KDI", "BOK"):
        source_b_review = [row for row in b_review_rows if row["source"] == source]
        b_review_by_source[source] = len(source_b_review)
        b_review_disagreement_by_source[source] = sum(
            row["label_a"] is not None
            and row["label_b"] is not None
            and row["label_a"] != row["label_b"]
            for row in source_b_review
        )
    keyword_candidates = [row for row in keyword_rows if row["keyword_candidate"]]
    hybrid_observed = [row for row in hybrid_rows if row["predicted_label"] is not None]
    full_quality_path = ROOT / "reports" / "full_dataset_validation.json"
    full_quality = {}
    if full_quality_path.is_file():
        full_quality = json.loads(full_quality_path.read_text(encoding="utf-8")).get(
            "quality_issues", {}
        )
    return {
        "status": "EXECUTED_NOTEBOOK_BACKING_ARTIFACTS",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notebook": "notebook/precision_eda.ipynb",
        "random_seed": RANDOM_SEED,
        "chapter": summary.get("chapter", {}),
        "dataset": {
            "canonical_document_count": summary["corpus_inventory"]["document_count"],
            "canonical_document_count_by_source": summary["corpus_inventory"]["document_count_by_source"],
            "canonical_chunk_count": 3545,
            "canonical_token_total_from_latest_eda": 770607,
            "labeled_sample_count": summary["combined_row_count"],
            "labeled_sample_count_by_source": summary["source_row_counts"],
            "dataset_version": summary["dataset_version"],
            "workbooks": summary["workbooks"],
        },
        "data_quality": source_quality,
        "full_corpus_quality": full_quality,
        "labels": {
            "distributions": label_distributions,
            "agreement": agreement["by_source"],
            "b_review_flag_count": len(b_review_rows),
            "b_review_flag_and_ab_disagreement_count": b_review_disagreements,
            "b_review_flag_count_by_source": b_review_by_source,
            "b_review_flag_and_ab_disagreement_count_by_source": b_review_disagreement_by_source,
            "ab_disagreement_count_is_not_b_review_count": True,
            "provenance_policy": "AI_REVIEW_AGREEMENT; not HUMAN_INTER_RATER_AGREEMENT",
        },
        "methods": {
            "keyword_only": {
                "status": methods["keyword_only"]["status"],
                "evaluated_docs": methods["keyword_only"]["coverage_count"],
                "candidate_docs": len(keyword_candidates),
                "candidate_rate": len(keyword_candidates) / len(keyword_rows) if keyword_rows else None,
                "proxy_question": methods["keyword_only"]["question_generation"],
                "proxy_tutor": methods["keyword_only"]["tutor_retrieval"],
            },
            "llm_only": {
                "status": methods["llm_only"]["status"],
                "evaluated_docs": methods["llm_only"]["coverage_count"],
                "coverage_rate": methods["llm_only"]["coverage_count"] / len(rows) if rows else None,
                "proxy_question": methods["llm_only"]["question_generation"],
                "proxy_tutor": methods["llm_only"]["tutor_retrieval"],
                "model": sorted({row["model"] for row in llm_observed if row["model"]}),
                "prompt_versions": sorted({row["prompt_version"] for row in llm_observed if row["prompt_version"]}),
                "json_parse_failure_count": parse_failures,
                "evidence_validation_failure_count": evidence_failures,
                "latency_ms_mean": statistics.mean(latencies) if latencies else None,
                "latency_ms_p95": sorted(latencies)[max(0, math.ceil(len(latencies) * 0.95) - 1)] if latencies else None,
                "input_tokens": sum(row["input_tokens"] or 0 for row in llm_observed),
                "output_tokens": sum(row["output_tokens"] or 0 for row in llm_observed),
                "cost_usd": None,
                "cost_status": "UNCONFIRMED_CONFIG_REQUIRED",
            },
            "hybrid": {
                "status": methods["hybrid"]["status"],
                "evaluated_docs": methods["hybrid"]["coverage_count"],
                "observed_prediction_docs": len(hybrid_observed),
                "population_docs": len(rows),
                "keyword_negative_docs": methods["hybrid"]["keyword_negative_docs"],
                "keyword_candidate_docs": methods["hybrid"]["keyword_candidate_docs"],
                "candidate_llm_observed_docs": methods["hybrid"]["candidate_llm_observed_docs"],
                "candidate_llm_not_observed_docs": methods["hybrid"]["candidate_llm_not_observed_docs"],
                "pending_docs": methods["hybrid"]["pending_docs"],
                "prediction_status_counts": dict(
                    Counter(row["prediction_status"] for row in hybrid_rows)
                ),
                "proxy_question": methods["hybrid"]["question_generation"],
                "proxy_tutor": methods["hybrid"]["tutor_retrieval"],
            },
        },
        "independent_gold": {
            "status": "NOT_READY",
            "count": 0,
            "path": display_path(DEFAULT_GOLD),
        },
        "final_metrics_policy": "NOT_EVALUATED_UNTIL_INDEPENDENT_GOLD_APPROVED",
        "new_api_calls": int(api_execution.get("llm_calls", 0)),
        "llm_execution": api_execution,
        "reference_disagreement_count": len(errors),
        "plots": plot_paths,
        "artifacts": {
            "combined_jsonl": "data/processed/evaluation/combined_320.jsonl",
            "label_disagreements": "reports/evaluation/label_disagreements.csv",
            "keyword_predictions": "reports/evaluation/keyword_predictions.csv",
            "llm_predictions": "reports/evaluation/llm_predictions.csv",
            "hybrid_predictions": "reports/evaluation/hybrid_predictions.csv",
            "method_comparison": "reports/evaluation/method_comparison.json",
            "precision_eda_report": "reports/evaluation/precision_eda_report.md",
        },
    }


def _precision_eda_report(summary: dict[str, Any]) -> str:
    """Render the notebook-facing report from the executed summary."""
    agreement = summary["labels"]["agreement"]
    methods = summary["methods"]
    lines = [
        "# Leren precision EDA 실행 보고서",
        "",
        "## 1. 연구 개요",
        "",
        "인플레이션 챕터 문서 선별을 위해 KDI·BOK 라벨링 표본과 canonical corpus를 연결하고 Keyword-only, LLM-only, Hybrid 결과를 비교했다.",
        "문제 생성은 관련도 2, Tutor 선별은 관련도 1 또는 2를 양성으로 보는 별도 정책을 사용한다.",
        "",
        "## 2. 데이터셋 및 검증",
        "",
        f"- 전체 corpus: {summary['dataset']['canonical_document_count']}건; KDI/BOK: {summary['dataset']['canonical_document_count_by_source']}",
        f"- 라벨링 표본: {summary['dataset']['labeled_sample_count']}건; 기관별: {summary['dataset']['labeled_sample_count_by_source']}",
        f"- dataset_version: `{summary['dataset']['dataset_version']}`; chunk: {summary['dataset']['canonical_chunk_count']}개; token: {summary['dataset']['canonical_token_total_from_latest_eda']:,}개",
        "- 원본 Excel은 읽기 전용이며, BOK `확정 골드=완료`는 숫자 Gold로 변환하지 않았다.",
        "- 전체 corpus 품질 검토는 Notebook 실행 시점의 `full_dataset_validation.json`을 함께 참조한다.",
        f"- BOK source_url 누락: {summary.get('full_corpus_quality', {}).get('bok_source_url_missing', {}).get('count', 'NOT_AVAILABLE')}건; license 미확정: {summary.get('full_corpus_quality', {}).get('license_status_unconfirmed', {}).get('count', 'NOT_AVAILABLE')}건",
        f"- 20토큰 미만: {summary.get('full_corpus_quality', {}).get('under_20_tokens', {}).get('count', 'NOT_AVAILABLE')}건; 청크 제한 초과: {summary.get('full_corpus_quality', {}).get('over_chunk_limit', {}).get('count', 'NOT_AVAILABLE')}건; 동일 본문 hash 그룹: {summary.get('full_corpus_quality', {}).get('duplicate_content_hash_within_source', {}).get('count', 'NOT_AVAILABLE')}건",
        "",
        "## 3. 라벨링 및 A/B 일치도",
        "",
        "A/B 수치는 독립 인간 평가자 간 일치도가 아닌 `AI_REVIEW_AGREEMENT`로만 해석한다.",
        "",
        "| 기관 | 비교 | 일치 | 불일치 | 일치율 | Kappa |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for source in ("KDI", "BOK", "ALL"):
        item = agreement[source]
        lines.append(f"| {source} | {item['comparable_count']} | {item['agree_count']} | {item['disagree_count']} | {item['agreement_rate']:.4f} | {item['cohen_kappa']:.4f} |")
    lines.extend(
        [
            "",
            f"B 재검토 대상: 전체 {summary['labels']['b_review_flag_count']}건 (KDI {summary['labels']['b_review_flag_count_by_source']['KDI']}건, BOK {summary['labels']['b_review_flag_count_by_source']['BOK']}건), 그중 A/B 불일치: 전체 {summary['labels']['b_review_flag_and_ab_disagreement_count']}건 (KDI {summary['labels']['b_review_flag_and_ab_disagreement_count_by_source']['KDI']}건, BOK {summary['labels']['b_review_flag_and_ab_disagreement_count_by_source']['BOK']}건). 두 수치는 별도 개념이다.",
            "",
            "## 4. 방법별 실행 결과",
            "",
            "| 방법 | 상태 | 평가 문서 | 주요 결과 |",
            "|---|---|---:|---|",
            f"| Keyword-only | {methods['keyword_only']['status']} | {methods['keyword_only']['evaluated_docs']} | 후보 {methods['keyword_only']['candidate_docs']}건 ({methods['keyword_only']['candidate_rate']:.1%}) |",
            f"| LLM-only | {methods['llm_only']['status']} | {methods['llm_only']['evaluated_docs']} | 파일럿 커버리지 {methods['llm_only']['coverage_rate']:.1%} |",
            f"| Hybrid | {methods['hybrid']['status']} | {methods['hybrid']['evaluated_docs']} | 관측 {methods['hybrid']['observed_prediction_docs']}건; 미관측 후보 {methods['hybrid']['candidate_llm_not_observed_docs']}건 |",
            "",
            "## 5. Precision / Recall / F1",
            "",
            f"독립 Gold 상태: `{summary['independent_gold']['status']}`, 건수: {summary['independent_gold']['count']}. 따라서 최종 Precision·Recall·F1은 `NOT_EVALUATED`이다.",
            "현재 proxy 값은 Workbook/A-B 합의 참고 라벨과의 예비 일치도이며 최종 모델 성능으로 보고하지 않는다.",
            "",
            "## 6. 한계 및 다음 개발",
            "",
            f"- Keyword/reference 판정 불일치 사례: {summary['reference_disagreement_count']}건; 독립 Gold 전에는 오분류로 확정하지 않는다.",
            f"- LLM 실행 상태: `{summary.get('llm_execution', {}).get('status', 'NOT_EXECUTED')}`; 신규 API 호출: {summary['new_api_calls']}건; 기록된 API 호출: {summary.get('llm_execution', {}).get('recorded_api_calls', summary['new_api_calls'])}건.",
            "- 독립 Gold 승인 후 동일한 평가 모수로 두 목적별 TP/FP/FN/TN과 P/R/F1을 산출한다.",
            "- 키워드 미적중 문서, 품질 검토필요 문서, A/B 불일치 문서를 독립 검수 표본에 포함한다.",
            "",
            "## 7. 산출물",
            "",
        ]
    )
    lines.extend(f"- `{path}`" for path in summary["artifacts"].values())
    return "\n".join(lines) + "\n"


def _write_notebook(path: Path) -> None:
    notebook = {
        "cells": [
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "# Leren KDI/BOK 320 평가 EDA\n",
                    "통합 실행 결과를 다시 읽어 데이터 규모, 원문 대조, A/B 일치도, 방법별 커버리지를 확인한다.\n",
                    "외부 LLM은 호출하지 않았으며 독립 Gold가 없어 최종 P/R/F1은 생성하지 않는다.",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# ruff: noqa: E501\n",
                    "import json\n",
                    "import csv\n",
                    "from pathlib import Path\n",
                    "\n",
                    "ROOT = Path.cwd()\n",
                    "while not (ROOT / 'app').is_dir() and ROOT != ROOT.parent:\n",
                    "    ROOT = ROOT.parent\n",
                    "\n",
                    "summary_path = ROOT / 'reports/evaluation/combined_320_summary.json'\n",
                    "agreement_path = ROOT / 'reports/evaluation/label_agreement_report.json'\n",
                    "method_path = ROOT / 'reports/evaluation/method_comparison.json'\n",
                    "summary = json.loads(summary_path.read_text())\n",
                    "agreement = json.loads(agreement_path.read_text())\n",
                    "methods = json.loads(method_path.read_text())\n",
                    "print('통합 행 수:', summary['combined_row_count'])\n",
                    "print('기관별 행 수:', summary['source_row_counts'])\n",
                    "print('독립 Gold:', methods['independent_gold'])\n",
                    "print('신규 API 호출:', methods['new_api_calls'])\n",
                    "print('A/B:', {source: (item['agree_count'], item['disagree_count']) for source, item in agreement['by_source'].items()})\n",
                    "print('방법별 상태:', {name: (item['status'], item['coverage_count']) for name, item in methods['methods'].items() if name in ('keyword_only', 'llm_only', 'hybrid')})\n",
                    "display_columns = ['source', 'document_id', 'title', 'label_a', 'label_b', 'proposed_final_label', 'label_provenance']\n",
                    "with (ROOT / 'data/processed/evaluation/combined_320.jsonl').open(encoding='utf-8') as handle:\n",
                    "    rows = [json.loads(line) for line in handle if line.strip()]\n",
                    "print('통합 데이터 샘플:')\n",
                    "for row in rows[:10]:\n",
                    "    print({column: row.get(column) for column in display_columns})\n",
                ],
            },
            {
                "cell_type": "code",
                "execution_count": None,
                "metadata": {},
                "outputs": [],
                "source": [
                    "# ruff: noqa\n",
                    "import csv\n",
                    "from IPython.display import display\n",
                    "evaluation_dir = ROOT / 'reports/evaluation'\n",
                    "def preview_csv(path, limit=10):\n",
                    "    with path.open(encoding='utf-8-sig', newline='') as handle:\n",
                    "        return list(csv.DictReader(handle))[:limit]\n",
                    "display(preview_csv(evaluation_dir / 'label_disagreements.csv'))\n",
                    "display(preview_csv(evaluation_dir / 'keyword_predictions.csv'))\n",
                    "print('최종 metric 그래프 상태:', methods['gold_metric_plots']['status'])\n",
                ],
            },
            {
                "cell_type": "markdown",
                "metadata": {},
                "source": [
                    "## 정책\n",
                    "Workbook 라벨은 AI/reference proxy로만 사용한다. `GOLD_APPROVED`가 없는 상태에서 Precision/Recall/F1을 확정하지 않는다.",
                ],
            },
        ],
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3",
            },
            "language_info": {"name": "python"},
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(notebook, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def run(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    combined_path: Path = DEFAULT_COMBINED,
    pilot_path: Path = DEFAULT_PILOT,
    data_dir: Path = ROOT / "data",
    chapter_path: Path = ROOT / "configs" / "chapters.yaml",
    kdi_workbook: Path | None = None,
    bok_workbook: Path | None = None,
    execute_llm: bool = False,
    llm_sample_size: int = 20,
) -> dict[str, Any]:
    rows, summary = build_combined_dataset(data_dir, kdi_workbook, bok_workbook)
    chapter = load_chapter(chapter_path)
    summary["chapter"] = {
        "id": chapter.chapter_id,
        "status": load_yaml(chapter_path).get("curriculum_status"),
        "rubric_version": chapter.rubric_version,
    }
    tokenizer = ExactTokenizer(TOKENIZER_NAME)
    pilot_execution: dict[str, Any]
    if execute_llm:
        if not 1 <= llm_sample_size <= 20:
            raise ValueError("--llm-sample-size must be between 1 and 20")
        selected_workbooks = [
            Path(summary["workbooks"][source]["selected"]["absolute_path"])
            for source in ("KDI", "BOK")
        ]
        pilot_execution = run_llm_pilot(
            chapter_path=chapter_path,
            output_path=pilot_path,
            sample_size=llm_sample_size,
            execute=True,
            workbook_paths=selected_workbooks,
        )
        pilot_execution["status"] = "EXECUTED_LLM_PILOT"
        pilot_execution["recorded_api_calls"] = pilot_execution.get("llm_calls", 0)
    else:
        pilot_results = _load_llm_results(pilot_path)
        stored_api_rows = [
            row
            for row in pilot_results.values()
            if row.get("execution_mode") == "API_EXECUTED"
        ]
        pilot_execution = {
            "status": (
                "REUSED_EXECUTED_LLM_PILOT"
                if stored_api_rows
                else "REUSED_EXISTING_LLM_PILOT"
                if pilot_results
                else "NOT_EXECUTED"
            ),
            "llm_calls": 0,
            "recorded_api_calls": sum(
                int(row.get("llm_call_count", 0)) for row in stored_api_rows
            ),
            "sample_size": len(pilot_results),
            "output_path": display_path(pilot_path),
        }
    pilot_results = _load_llm_results(pilot_path)
    keyword_rows = run_keyword_predictions(rows, chapter, tokenizer)
    llm_rows = run_llm_predictions(rows, pilot_results)
    hybrid_rows = run_hybrid_predictions(rows, keyword_rows, llm_rows)
    agreement = label_agreement_report(rows)
    methods, overlap = _method_predictions(
        rows,
        keyword_rows,
        llm_rows,
        hybrid_rows,
        llm_execution_status=pilot_execution["status"],
    )
    errors = _error_rows(rows, keyword_rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(combined_path, rows)
    write_json(
        output_dir / "combined_320_summary.json",
        {
            **summary,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chapter": summary["chapter"],
        },
    )
    write_json(output_dir / "label_agreement_report.json", agreement)
    disagreement_rows = [
        {
            "source": row["source"],
            "document_id": row["document_id"],
            "title": row["title"],
            "label_a": row["label_a"],
            "label_b": row["label_b"],
            "reason": row["reason"],
            "keyword_label": row["keyword_label"],
            "sampling_bucket": row["sampling_bucket"],
            "data_quality_status": row["data_quality_status"],
            "b_review": row["b_review"],
            "review_status": "PENDING_HUMAN_REVIEW",
        }
        for row in rows
        if row["label_a"] is not None
        and row["label_b"] is not None
        and row["label_a"] != row["label_b"]
    ]
    write_csv(
        output_dir / "label_disagreements.csv",
        disagreement_rows,
        list(disagreement_rows[0]) if disagreement_rows else ["source", "document_id"],
    )
    write_csv(
        output_dir / "keyword_predictions.csv", keyword_rows, list(keyword_rows[0])
    )
    write_csv(output_dir / "llm_predictions.csv", llm_rows, list(llm_rows[0]))
    write_csv(output_dir / "hybrid_predictions.csv", hybrid_rows, list(hybrid_rows[0]))
    method_result = {
        "status": "EXECUTED_LLM_PILOT"
        if execute_llm
        else "DRY_RUN_AI_REFERENCE",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "independent_gold": {
            "status": "NOT_READY",
            "count": 0,
            "path": display_path(DEFAULT_GOLD),
        },
        "new_api_calls": pilot_execution.get("llm_calls", 0)
        if execute_llm
        else 0,
        "existing_pilot_rows_reused": 0 if execute_llm else len(pilot_results),
            "llm_execution": pilot_execution,
        "model": sorted({row["model"] for row in llm_rows if row["model"]}),
        "prompt_versions": sorted(
            {row["prompt_version"] for row in llm_rows if row["prompt_version"]}
        ),
        "llm_threshold": LLM_THRESHOLD,
        "methods": methods,
        "pilot_overlap": overlap,
        "cost": {"status": "UNCONFIRMED_CONFIG_REQUIRED", "estimated_cost_usd": None},
        "gold_metric_plots": {
            "status": "NOT_GENERATED_INDEPENDENT_GOLD_REQUIRED",
            "precision": "reports/evaluation/precision_comparison.png",
            "recall": "reports/evaluation/recall_comparison.png",
            "f1": "reports/evaluation/f1_comparison.png",
        },
        "policy": {
            "question_generation_positive": "label == 2",
            "tutor_retrieval_positive": "label in {1,2}",
            "automatic_gold_approval": False,
        },
    }
    write_json(output_dir / "method_comparison.json", method_result)
    method_csv = []
    for method in ("keyword_only", "llm_only", "hybrid"):
        item = methods[method]
        method_csv.append(
            {
                "method": method,
                "status": item["status"],
                "population_count": item["population_count"],
                "coverage_count": item["coverage_count"],
                "pending_count": item.get("pending_docs", 0),
                "question_proxy_f1": (item["question_generation"]["metrics"] or {}).get(
                    "f1"
                ),
                "tutor_proxy_f1": (item["tutor_retrieval"]["metrics"] or {}).get("f1"),
            }
        )
    write_csv(output_dir / "method_comparison.csv", method_csv, list(method_csv[0]))
    write_json(
        output_dir / "error_analysis.json",
        {"status": "REFERENCE_DISAGREEMENT_ONLY", "count": len(errors), "rows": errors},
    )
    plot_paths = _write_plot_files(
        output_dir, rows, keyword_rows, llm_rows, hybrid_rows, methods
    )
    precision_eda_summary = _precision_eda_summary(
        summary,
        agreement,
        methods,
        rows,
        keyword_rows,
        llm_rows,
        hybrid_rows,
        plot_paths,
        errors,
        api_execution=pilot_execution,
    )
    write_json(output_dir / "precision_eda_summary.json", precision_eda_summary)
    (output_dir / "precision_eda_report.md").write_text(
        _precision_eda_report(precision_eda_summary), encoding="utf-8"
    )
    source_reports = summary["source_reports"]
    data_quality_lines = [
        "# Data quality report",
        "",
        "이 보고서는 원본 Excel·canonical JSON/JSONL을 읽기 전용으로 대조한 결과다.",
        "",
        "| 항목 | KDI | BOK | 전체 |",
        "|---|---:|---:|---:|",
        f"| 통합 행 | {source_reports['KDI']['row_count']} | {source_reports['BOK']['row_count']} | {summary['combined_row_count']} |",
        f"| 열 수 | {source_reports['KDI']['column_count']} | {source_reports['BOK']['column_count']} | - |",
        f"| 원문 EXACT_MATCH | {source_reports['KDI']['reconciliation_counts'].get('EXACT_MATCH', 0)} | {source_reports['BOK']['reconciliation_counts'].get('EXACT_MATCH', 0)} | {sum(report['reconciliation_counts'].get('EXACT_MATCH', 0) for report in source_reports.values())} |",
        f"| 원문 NORMALIZED_MATCH | {source_reports['KDI']['reconciliation_counts'].get('NORMALIZED_MATCH', 0)} | {source_reports['BOK']['reconciliation_counts'].get('NORMALIZED_MATCH', 0)} | {sum(report['reconciliation_counts'].get('NORMALIZED_MATCH', 0) for report in source_reports.values())} |",
        f"| 원문 CONTENT_MISMATCH | {source_reports['KDI']['reconciliation_counts'].get('CONTENT_MISMATCH', 0)} | {source_reports['BOK']['reconciliation_counts'].get('CONTENT_MISMATCH', 0)} | {sum(report['reconciliation_counts'].get('CONTENT_MISMATCH', 0) for report in source_reports.values())} |",
        f"| source_not_found | {source_reports['KDI']['reconciliation_counts'].get('SOURCE_NOT_FOUND', 0)} | {source_reports['BOK']['reconciliation_counts'].get('SOURCE_NOT_FOUND', 0)} | {sum(report['reconciliation_counts'].get('SOURCE_NOT_FOUND', 0) for report in source_reports.values())} |",
        f"| 숫자형 확정 골드 | {source_reports['KDI']['explicit_gold_numeric_count']} | {source_reports['BOK']['explicit_gold_numeric_count']} | - |",
        "",
        "## 라벨·품질 보류",
        "",
        f"- KDI `자료 품질=검토필요`: {source_reports['KDI']['validation']['integrity']['quality_distribution'].get('검토필요', 0)}건",
        f"- BOK `자료 품질=검토필요`: {source_reports['BOK']['validation']['integrity']['quality_distribution'].get('검토필요', 0)}건",
        f"- BOK `원본 점검플래그` 입력: {source_reports['BOK']['validation']['integrity']['original_quality_flag_count']}건",
        f"- BOK `확정 골드` 비수치 값: {source_reports['BOK']['explicit_gold_nonnumeric_values']}; 이는 상태값이며 0/1/2로 변환하지 않았다.",
        f"- 중복 document_id: {len(summary['duplicate_document_ids'])}건; ID 형식 오류: {len(summary['invalid_document_ids'])}건",
        "- 독립 Gold 승인 문서: 0건 (`NOT_READY`)",
        "",
        "원문·제목·source locator 불일치는 통합 행에 상태 필드로 보존되며 자동 수정하지 않는다.",
        "",
    ]
    (output_dir / "data_quality_report.md").write_text(
        "\n".join(data_quality_lines), encoding="utf-8"
    )
    (output_dir / "error_analysis.md").write_text(
        "# Error / disagreement analysis\n\n독립 Gold가 없어 오분류로 확정하지 않고 reference 불일치 사례로 기록했습니다. 상세 행은 `error_analysis.json`에 있습니다.\n\n"
        + "\n".join(
            f"- {row['case']} / {row['source']} / {row['document_id']} / {row['title']}"
            for row in errors[:100]
        )
        + "\n",
        encoding="utf-8",
    )
    report = _report_markdown(
        summary,
        agreement,
        methods,
        errors,
        plot_paths,
        sum(row["keyword_candidate"] for row in keyword_rows),
        sum(row["prediction_status"] != "NOT_EXECUTED" for row in llm_rows),
        api_execution=pilot_execution,
    )
    (output_dir / "evaluation_report.md").write_text(report, encoding="utf-8")
    (ROOT / "Leren_KDI_BOK_Classification_Report.md").write_text(
        report, encoding="utf-8"
    )
    _write_notebook(output_dir / "evaluation_eda.ipynb")
    return {
        "summary": summary,
        "agreement": agreement,
        "methods": method_result,
        "error_count": len(errors),
        "output_dir": display_path(output_dir),
        "plot_paths": plot_paths,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--kdi-workbook", type=Path)
    parser.add_argument("--bok-workbook", type=Path)
    parser.add_argument("--pilot", type=Path, default=DEFAULT_PILOT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--combined", type=Path, default=DEFAULT_COMBINED)
    parser.add_argument(
        "--execute-llm",
        action="store_true",
        help="KDI/BOK 균형 표본에 대해 최대 20건의 외부 LLM 호출을 명시적으로 실행합니다.",
    )
    parser.add_argument(
        "--llm-sample-size",
        type=int,
        default=20,
        help="API 파일럿 요청 수(1~20). 전체 320건 호출은 이 옵션으로 허용하지 않습니다.",
    )
    args = parser.parse_args()
    result = run(
        args.output_dir,
        args.combined,
        args.pilot,
        args.data_dir,
        ROOT / "configs" / "chapters.yaml",
        args.kdi_workbook,
        args.bok_workbook,
        args.execute_llm,
        args.llm_sample_size,
    )
    print(
        json.dumps(
            {
                "status": result["methods"]["status"],
                "combined_row_count": result["summary"]["combined_row_count"],
                "error_count": result["error_count"],
                "output_dir": result["output_dir"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
