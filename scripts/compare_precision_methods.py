"""Compare Keyword-only, LLM-only, and Keyword+LLM Hybrid methods.

This script is deliberately conservative.  It does not treat the current
``라벨링.xlsx`` workbook as an independent test set and therefore produces a
dry-run readiness report until a separately reviewed Gold Set is supplied.
When an independent Gold Set is available, the same rows and the same binary
policy are used for all three methods.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import statistics
import sys
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
    validate_relevance_score,
)
from app.dataset_pipeline.io import load_corpus  # noqa: E402
from app.dataset_pipeline.keywords import Chapter, classify_chunk_by_keywords  # noqa: E402
from app.dataset_pipeline.labels import (  # noqa: E402
    analyze_label_rows,
    discover_label_workbook,
    read_xlsx_rows,
)
from app.dataset_pipeline.tokenizer import ExactTokenizer  # noqa: E402
from scripts._pipeline_support import load_yaml  # noqa: E402
from scripts.rebuild_precision_pipeline import _make_chunk, _records  # noqa: E402

DEFAULT_CHAPTERS = ROOT / "configs/chapters.yaml"
DEFAULT_GOLD = ROOT / "reports/independent_gold_test.csv"
DEFAULT_LLM_RESULTS = ROOT / "data/labeled/precision/llm_pilot_results.jsonl"
DEFAULT_OUTPUT = ROOT / "reports/method_comparison_result.json"
DEFAULT_PREDICTIONS = ROOT / "data/labeled/precision/method_predictions.csv"
DEFAULT_FAILURES = ROOT / "data/labeled/precision/method_failures.csv"
DEFAULT_PLOT = ROOT / "reports/method_comparison_metrics.png"
DEFAULT_THRESHOLDS = (0.5, 0.6, 0.7, 0.8, 0.9)


def _text(value: object) -> str:
    """Normalize CSV/XLSX values without inventing missing labels."""
    text = "" if value is None else str(value).strip()
    return "" if text.casefold() in {"", "none", "null", "nan"} else text


def _display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _write_csv(
    path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def _load_chapter(path: Path) -> Chapter:
    payload = load_yaml(path)
    chapters = payload.get("chapters", [])
    if not chapters:
        raise ValueError(f"{path}에 챕터가 없습니다.")
    return Chapter.from_dict(chapters[0])


def _canonical_source_records(data_dir: Path) -> dict[str, dict[str, Any]]:
    """Load both KDI and BOK source records without counting mirror exports twice."""
    documents, _ = load_corpus(data_dir)
    return {
        document.document_id: {
            "row_number": None,
            "document_id": document.document_id,
            "title": document.title,
            "content": document.content,
            "source": document.source,
            "source_group": document.source,
            "source_locator": document.source_locator or "",
            "gold_score": None,
            "reviewer_a": None,
            "reviewer_b": None,
            "quality": document.source_review_status,
            "quality_flag": "",
            "quiz_suitable": None,
            "tutor_suitable": None,
            "reason": "",
            "keyword_label": "",
            "binary_label": "",
            "b_review": "",
        }
        for document in documents
    }


def _independent_gold_status(
    path: Path, evaluation_split: str = "test"
) -> dict[str, Any]:
    """Validate the provenance marker required for final metrics."""
    if not path.is_file():
        return {
            "status": "MISSING",
            "path": _display_path(path),
            "reason": "별도 독립 Gold CSV가 아직 없습니다.",
            "row_count": 0,
            "valid_row_count": 0,
        }
    rows = _read_csv(path)
    required = {
        "document_id",
        "content_hash",
        "source_group",
        "split",
        "gold_score",
        "gold_set_status",
        "review_status",
        "reviewer_count",
        "review_mode",
    }
    missing_columns = sorted(required - set(rows[0]) if rows else required)
    if missing_columns:
        return {
            "status": "INVALID_SCHEMA",
            "path": _display_path(path),
            "reason": "독립성·검수 상태를 확인할 필드가 없습니다.",
            "missing_columns": missing_columns,
            "row_count": len(rows),
            "valid_row_count": 0,
        }

    duplicate_ids = len(rows) - len({_text(row.get("document_id")) for row in rows})
    evaluation_rows = [
        row for row in rows if _text(row.get("split")) == evaluation_split
    ]
    invalid_labels: list[str] = []
    invalid_document_ids: list[str] = []
    invalid_split_rows: list[str] = []
    invalid_status_rows: list[str] = []
    invalid_review_rows: list[str] = []
    for row in evaluation_rows:
        document_id = _text(row.get("document_id"))
        if not document_id or not _text(row.get("content_hash")):
            invalid_document_ids.append(document_id)
        if _text(row.get("split")) not in {"development", "test"}:
            invalid_split_rows.append(document_id)
        try:
            validate_relevance_score(_text(row.get("gold_score")))
        except ValueError:
            invalid_labels.append(document_id)
        if _text(row.get("gold_set_status")) != "INDEPENDENT_APPROVED":
            invalid_status_rows.append(document_id)
        if _text(row.get("review_status")) != "APPROVED":
            invalid_status_rows.append(document_id)
        try:
            reviewer_count = int(_text(row.get("reviewer_count")))
        except (TypeError, ValueError):
            reviewer_count = 0
        review_mode = _text(row.get("review_mode"))
        if review_mode == "ADJUDICATED_CONSENSUS" and reviewer_count < 2:
            invalid_review_rows.append(document_id)
        elif review_mode == "THIRD_PARTY_REVIEW" and reviewer_count < 1:
            invalid_review_rows.append(document_id)
        elif review_mode not in {"ADJUDICATED_CONSENSUS", "THIRD_PARTY_REVIEW"}:
            invalid_review_rows.append(document_id)

    valid = (
        bool(evaluation_rows)
        and not duplicate_ids
        and not invalid_document_ids
        and not invalid_split_rows
        and not invalid_labels
        and not invalid_status_rows
        and not invalid_review_rows
    )
    return {
        "status": "READY" if valid else "NOT_INDEPENDENT",
        "path": _display_path(path),
        "reason": (
            "독립 검수 완료 표본으로 확인되었습니다."
            if valid
            else "독립 검수 상태, 검수자 수·방식, 관련도 값이 모두 유효해야 합니다."
        ),
        "row_count": len(rows),
        "evaluation_split": evaluation_split,
        "evaluation_row_count": len(evaluation_rows),
        "valid_row_count": len(evaluation_rows) if valid else 0,
        "duplicate_id_count": duplicate_ids,
        "invalid_label_ids": sorted(set(invalid_labels)),
        "invalid_document_ids": sorted(set(invalid_document_ids)),
        "invalid_split_ids": sorted(set(invalid_split_rows)),
        "invalid_status_ids": sorted(set(invalid_status_rows)),
        "invalid_review_ids": sorted(set(invalid_review_rows)),
        "rows": evaluation_rows if valid else [],
    }


def _load_llm_results(path: Path) -> dict[str, dict[str, Any]]:
    """Load one latest LLM result per document without changing its review state."""
    if not path.is_file():
        return {}
    results: dict[str, dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        document_id = _text(row.get("document_id"))
        if document_id:
            results[document_id] = row
    return results


def _keyword_predictions(
    records: list[dict[str, Any]], chapter: Chapter, tokenizer: ExactTokenizer
) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    for record in records:
        result = classify_chunk_by_keywords(_make_chunk(record, tokenizer), chapter)
        predictions.append(
            {
                "document_id": record["document_id"],
                "title": record["title"],
                "content": record["content"],
                "keyword_candidate": bool(result["candidate"]),
                "matched_keywords": json.dumps(
                    result["matched_keywords"], ensure_ascii=False
                ),
                "keyword_evidence": result["evidence_span"] or "",
                "keyword_review_status": "PENDING",
            }
        )
    return predictions


def _binary_metrics(
    predictions: dict[str, bool],
    gold_rows: dict[str, int],
    usage: str,
) -> dict[str, Any]:
    gold_ids = set(gold_rows)
    prediction_ids = set(predictions)
    missing_ids = sorted(gold_ids - prediction_ids)
    extra_ids = sorted(prediction_ids - gold_ids)
    # 미예측 문서를 조용히 제외하면 지표가 부풀려질 수 있으므로,
    # 독립 Gold 전체에 대한 예측이 없을 때는 최종 지표를 계산하지 않습니다.
    if missing_ids:
        return {
            "status": "NOT_EVALUATED_INCOMPLETE_PREDICTIONS",
            "population_count": 0,
            "matrix": None,
            "metrics": None,
            "missing_prediction_count": len(missing_ids),
            "missing_prediction_ids": missing_ids[:100],
            "extra_prediction_count": len(extra_ids),
            "extra_prediction_ids": extra_ids[:100],
            "usage": usage,
        }

    joined_ids = sorted(gold_ids)
    predicted_values = [predictions[document_id] for document_id in joined_ids]
    gold_values = [
        positive_for_use(gold_rows[document_id], usage) for document_id in joined_ids
    ]
    matrix = confusion_matrix(predicted_values, gold_values)
    return {
        "status": "EVALUATED",
        "population_count": len(joined_ids),
        "matrix": matrix,
        "metrics": precision_recall_f1(matrix),
        "missing_prediction_count": len(set(gold_rows) - set(predictions)),
        "extra_prediction_count": len(set(predictions) - set(gold_rows)),
        "extra_prediction_ids": extra_ids[:100],
        "usage": usage,
    }


def _threshold_prediction(
    llm_results: dict[str, dict[str, Any]],
    threshold: float,
    allowed_ids: set[str] | None = None,
) -> dict[str, bool]:
    output: dict[str, bool] = {}
    for document_id, row in llm_results.items():
        if allowed_ids is not None and document_id not in allowed_ids:
            continue
        score = row.get("relevance_score")
        if isinstance(score, bool) or not isinstance(score, (int, float)):
            continue
        output[document_id] = float(score) >= threshold
    return output


def _hybrid_prediction(
    llm_results: dict[str, dict[str, Any]],
    threshold: float,
    candidate_ids: set[str],
    evaluation_ids: set[str],
) -> dict[str, bool]:
    """Represent non-candidates as explicit negatives for complete evaluation."""
    # 후보 밖의 문서를 결과에서 삭제하지 않고 명시적 음성으로 남겨
    # 세 가지 방식이 동일한 평가 모집단을 사용하도록 합니다.
    predictions = {document_id: False for document_id in evaluation_ids}
    predictions.update(_threshold_prediction(llm_results, threshold, candidate_ids))
    return predictions


def _latency_summary(llm_results: dict[str, dict[str, Any]]) -> dict[str, Any]:
    values = [
        float(row["latency_seconds"])
        for row in llm_results.values()
        if isinstance(row.get("latency_seconds"), (int, float))
    ]
    if not values:
        return {"count": 0, "average_seconds": None, "p95_seconds": None}
    return {
        "count": len(values),
        "average_seconds": round(statistics.mean(values), 4),
        "p95_seconds": round(
            sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)], 4
        ),
    }


def _cost_summary(
    llm_results: dict[str, dict[str, Any]], config_path: Path
) -> dict[str, Any]:
    """Calculate cost only when a configured price is explicitly available."""
    payload = load_yaml(config_path) if config_path.is_file() else {}
    models = payload.get("classification", {}).get("models", [])
    model_names = {str(row.get("model_name")) for row in llm_results.values()}
    selected = next((item for item in models if item.get("model") in model_names), None)
    input_tokens = sum(
        int(row.get("input_tokens_actual") or row.get("input_tokens_estimated") or 0)
        for row in llm_results.values()
    )
    output_tokens = sum(
        int(row.get("output_tokens_actual") or row.get("output_tokens_estimated") or 0)
        for row in llm_results.values()
    )
    input_price = selected.get("input_usd_per_1m_tokens") if selected else None
    output_price = selected.get("output_usd_per_1m_tokens") if selected else None
    cost = None
    if isinstance(input_price, (int, float)) and isinstance(output_price, (int, float)):
        cost = (
            input_tokens / 1_000_000 * input_price
            + output_tokens / 1_000_000 * output_price
        )
    return {
        "model_names": sorted(model_names),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "input_usd_per_1m_tokens": input_price,
        "output_usd_per_1m_tokens": output_price,
        "estimated_cost_usd": cost,
        "price_status": "CONFIRMED"
        if cost is not None
        else "UNCONFIRMED_CONFIG_REQUIRED",
    }


def _write_failure_rows(
    path: Path,
    predictions: dict[str, dict[str, bool]],
    gold_rows: dict[str, int],
    source_rows: dict[str, dict[str, Any]],
) -> None:
    rows: list[dict[str, Any]] = []
    for method, values in predictions.items():
        for usage in ("question_generation", "tutor_retrieval"):
            for document_id, predicted in values.items():
                if document_id not in gold_rows:
                    continue
                actual = positive_for_use(gold_rows[document_id], usage)
                if predicted == actual:
                    continue
                rows.append(
                    {
                        "method": method,
                        "usage": usage,
                        "document_id": document_id,
                        "title": source_rows.get(document_id, {}).get("title", ""),
                        "gold_score": gold_rows[document_id],
                        "predicted_positive": predicted,
                        "error_type": "FP" if predicted else "FN",
                        "error_cause": "UNREVIEWED_HUMAN_ERROR_ANALYSIS_REQUIRED",
                        "review_status": "PENDING",
                    }
                )
    _write_csv(
        path,
        rows,
        [
            "method",
            "usage",
            "document_id",
            "title",
            "gold_score",
            "predicted_positive",
            "error_type",
            "error_cause",
            "review_status",
        ],
    )


def run(
    workbook_path: Path | None = None,
    chapter_path: Path = DEFAULT_CHAPTERS,
    gold_path: Path = DEFAULT_GOLD,
    llm_results_path: Path = DEFAULT_LLM_RESULTS,
    output_path: Path = DEFAULT_OUTPUT,
    predictions_path: Path = DEFAULT_PREDICTIONS,
    failures_path: Path = DEFAULT_FAILURES,
    plot_path: Path = DEFAULT_PLOT,
    thresholds: Iterable[float] = DEFAULT_THRESHOLDS,
    tokenizer_name: str = "gpt-4o-mini",
    data_dir: Path = ROOT / "data",
) -> dict[str, Any]:
    """Run a dry-run or final comparison when an independent Gold Set exists."""
    workbook = workbook_path
    if workbook is None:
        candidates = discover_label_workbook(ROOT)
        if not candidates:
            raise FileNotFoundError("라벨링.xlsx 또는 라벨 파일을 찾지 못했습니다.")
        workbook = candidates[0]
    rows = read_xlsx_rows(workbook)
    analysis = analyze_label_rows(rows, workbook)
    records = _records(rows, analysis["detected_columns"])
    chapter = _load_chapter(chapter_path)
    tokenizer = ExactTokenizer(tokenizer_name)
    # Gold가 KDI와 BOK를 함께 포함할 수 있도록 canonical corpus를 기본 입력으로
    # 사용합니다. Excel의 KDI 행은 동일 ID의 canonical 행보다 우선합니다.
    try:
        source_rows = _canonical_source_records(data_dir)
    except (FileNotFoundError, ValueError):
        source_rows = {}
    source_rows.update({record["document_id"]: record for record in records})
    source_records = list(source_rows.values())
    keyword_rows = _keyword_predictions(source_records, chapter, tokenizer)
    keyword_map = {row["document_id"]: row["keyword_candidate"] for row in keyword_rows}
    llm_results = _load_llm_results(llm_results_path)
    gold_status = _independent_gold_status(gold_path)
    source_hashes = {
        document_id: hashlib.sha256(record["content"].encode("utf-8")).hexdigest()
        for document_id, record in source_rows.items()
    }
    hash_mismatch_ids = [
        _text(row.get("document_id"))
        for row in gold_status.get("rows", [])
        if _text(row.get("document_id")) in source_hashes
        and _text(row.get("content_hash"))
        != source_hashes[_text(row.get("document_id"))]
    ]
    missing_source_ids = [
        _text(row.get("document_id"))
        for row in gold_status.get("rows", [])
        if _text(row.get("document_id")) not in source_hashes
    ]
    if gold_status["status"] == "READY" and (hash_mismatch_ids or missing_source_ids):
        gold_status["status"] = "NOT_INDEPENDENT"
        gold_status["reason"] = (
            "Gold Set의 content_hash가 현재 평가 원문과 일치하지 않거나 "
            "원문 ID를 찾을 수 없습니다."
        )
        gold_status["content_hash_mismatch_ids"] = sorted(set(hash_mismatch_ids))
        gold_status["missing_source_ids"] = sorted(set(missing_source_ids))
        gold_status["rows"] = []
    gold_rows = {
        _text(row["document_id"]): int(_text(row["gold_score"]))
        for row in gold_status.get("rows", [])
    }
    target_ids = set(gold_rows) if gold_rows else set(source_rows)
    candidate_ids = {document_id for document_id, value in keyword_map.items() if value}
    llm_ids = set(llm_results)
    thresholds = tuple(sorted({float(value) for value in thresholds}))
    if any(not 0 <= value <= 1 for value in thresholds):
        raise ValueError("all thresholds must be between 0 and 1")

    method_predictions: dict[str, dict[str, bool]] = {
        "keyword_only": keyword_map,
    }
    for threshold in thresholds:
        key = f"llm_only@{threshold:.2f}"
        method_predictions[key] = _threshold_prediction(llm_results, threshold)
        key = f"hybrid@{threshold:.2f}"
        method_predictions[key] = _hybrid_prediction(
            llm_results,
            threshold,
            candidate_ids,
            set(source_rows),
        )

    metrics: dict[str, Any] = {}
    if gold_status["status"] == "READY":
        for method, prediction in method_predictions.items():
            metrics[method] = {
                usage: _binary_metrics(prediction, gold_rows, usage)
                for usage in ("question_generation", "tutor_retrieval")
            }
        all_methods_evaluated = all(
            usage_result["status"] == "EVALUATED"
            for method_result in metrics.values()
            for usage_result in method_result.values()
        )
        if all_methods_evaluated:
            _write_failure_rows(
                failures_path, method_predictions, gold_rows, source_rows
            )
            plot_status = _make_plot(plot_path, metrics, thresholds)
        else:
            plot_status = {
                "status": "NOT_GENERATED_INCOMPLETE_PREDICTIONS",
                "path": _display_path(plot_path),
            }
            _write_failure_rows(failures_path, {}, {}, source_rows)
    else:
        all_methods_evaluated = False
        plot_status = {
            "status": "NOT_GENERATED_INDEPENDENT_GOLD_REQUIRED",
            "path": _display_path(plot_path),
        }
        _write_failure_rows(failures_path, {}, {}, source_rows)

    readiness = {
        "source_row_count": len(source_rows),
        "keyword_candidate_count": len(candidate_ids),
        "keyword_candidate_unit": (
            "document_id; each source record is evaluated as one lineage-preserving "
            "anchor chunk"
        ),
        "keyword_candidate_rate": len(candidate_ids) / len(source_rows)
        if source_rows
        else 0,
        "llm_result_count": len(llm_ids),
        "llm_coverage_of_source": len(llm_ids & set(source_rows)) / len(source_rows)
        if source_rows
        else 0,
        "llm_coverage_of_keyword_candidates": len(llm_ids & candidate_ids)
        / len(candidate_ids)
        if candidate_ids
        else 0,
        "non_candidate_llm_sample_count": len(llm_ids - candidate_ids),
        "hybrid_non_candidate_sample_is_diagnostic_only": True,
    }
    result = {
        "status": (
            "EVALUATED_INDEPENDENT_GOLD"
            if gold_status["status"] == "READY" and all_methods_evaluated
            else (
                "NOT_EVALUATED_INCOMPLETE_PREDICTIONS"
                if gold_status["status"] == "READY"
                else "DRY_RUN_INDEPENDENT_GOLD_REQUIRED"
            )
        ),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "chapter_id": chapter.chapter_id,
        "chapter_config_status": load_yaml(chapter_path).get(
            "curriculum_status", "UNKNOWN"
        ),
        "input_file": _display_path(workbook),
        "source_corpus": _display_path(data_dir),
        "gold_set": {key: value for key, value in gold_status.items() if key != "rows"},
        "readiness": readiness,
        "thresholds": thresholds,
        "methods": metrics,
        "cost_and_latency": {
            "cost": _cost_summary(llm_results, ROOT / "configs/eda_config.yaml"),
            "latency": _latency_summary(llm_results),
        },
        "outputs": {
            "predictions_csv": _display_path(predictions_path),
            "failures_csv": _display_path(failures_path),
            "plot": plot_status,
        },
        "policy": {
            "problem_generation_positive": "gold_score == 2",
            "tutor_retrieval_positive": "gold_score in {1, 2}",
            "review_status_after_llm": "PENDING",
            "automatic_approval": False,
            "final_metrics_allowed_only_with_independent_gold": True,
            "all_gold_documents_must_have_predictions": True,
        },
    }
    prediction_rows = []
    for document_id in sorted(target_ids | (llm_ids & set(source_rows))):
        base = source_rows.get(document_id, {})
        prediction_rows.append(
            {
                "document_id": document_id,
                "title": base.get("title", ""),
                "keyword_only": keyword_map.get(document_id, False),
                "llm_relevance_score": llm_results.get(document_id, {}).get(
                    "relevance_score", ""
                ),
                "llm_review_status": llm_results.get(document_id, {}).get(
                    "review_status", ""
                ),
                "llm_provider_model": llm_results.get(document_id, {}).get(
                    "provider_response_model", ""
                ),
            }
        )
    _write_csv(
        predictions_path,
        prediction_rows,
        [
            "document_id",
            "title",
            "keyword_only",
            "llm_relevance_score",
            "llm_review_status",
            "llm_provider_model",
        ],
    )
    _write_json(output_path, result)
    return result


def _make_plot(
    path: Path, metrics: dict[str, Any], thresholds: tuple[float, ...]
) -> dict[str, Any]:
    """Create a compact comparison chart only for independent Gold results."""
    try:
        import matplotlib.pyplot as plt
    except ImportError:
        return {"status": "PLOT_DEPENDENCY_MISSING", "path": _display_path(path)}
    selected = ["keyword_only", f"llm_only@{0.7:.2f}", f"hybrid@{0.7:.2f}"]
    selected = [method for method in selected if method in metrics]
    labels = [method.replace("_", " ") for method in selected]
    figure, axes = plt.subplots(1, 2, figsize=(11, 4))
    for axis, usage in zip(axes, ("question_generation", "tutor_retrieval")):
        values = [metrics[method][usage]["metrics"] for method in selected]
        x = list(range(len(labels)))
        axis.bar(
            [index - 0.2 for index in x],
            [item["precision"] for item in values],
            width=0.2,
            label="Precision",
        )
        axis.bar(x, [item["recall"] for item in values], width=0.2, label="Recall")
        axis.bar(
            [index + 0.2 for index in x],
            [item["f1"] for item in values],
            width=0.2,
            label="F1",
        )
        axis.set_xticks(x, labels, rotation=20)
        axis.set_ylim(0, 1.05)
        axis.set_title("문제 생성" if usage == "question_generation" else "튜터 검색")
        axis.legend()
    figure.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(path, dpi=160)
    plt.close(figure)
    return {"status": "GENERATED", "path": _display_path(path), "threshold": 0.7}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=None)
    parser.add_argument("--chapters", type=Path, default=DEFAULT_CHAPTERS)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--llm-results", type=Path, default=DEFAULT_LLM_RESULTS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--failures", type=Path, default=DEFAULT_FAILURES)
    parser.add_argument("--plot", type=Path, default=DEFAULT_PLOT)
    parser.add_argument("--threshold", type=float, action="append", dest="thresholds")
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    args = parser.parse_args()
    result = run(
        workbook_path=args.workbook,
        chapter_path=args.chapters,
        gold_path=args.gold,
        llm_results_path=args.llm_results,
        output_path=args.output,
        predictions_path=args.predictions,
        failures_path=args.failures,
        plot_path=args.plot,
        thresholds=args.thresholds or DEFAULT_THRESHOLDS,
        data_dir=args.data_dir,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
