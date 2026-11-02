# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
"""Evaluate only explicit STEP 3 human labels; never infer missing Gold Labels."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PREDICTIONS = ROOT / "reports" / "step3" / "keyword_predictions.csv"
DEFAULT_GOLD = ROOT / "reports" / "step3" / "gold_label_template.csv"
DEFAULT_OUTPUT = ROOT / "reports" / "step3" / "evaluation_result.json"
VALID_LABELS = {"approved", "needs_review", "irrelevant"}
RESOLVED_LABELS = {"approved", "irrelevant"}


def read_csv(path: Path) -> list[dict[str, str]]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def prediction_label(row: dict[str, str]) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if row.get("keyword_label") in {"DIRECT", "INDIRECT"}:
        return "approved"
    return "irrelevant"


def binary_metrics(rows: list[dict[str, str]]) -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    positive = {"approved"}
    tp = sum(
        prediction_label(row) in positive and row["gold_label"] in positive
        for row in rows
    )
    fp = sum(
        prediction_label(row) in positive and row["gold_label"] not in positive
        for row in rows
    )
    fn = sum(
        prediction_label(row) not in positive and row["gold_label"] in positive
        for row in rows
    )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate(predictions_path: Path, gold_path: Path, scope: str) -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    predictions = read_csv(predictions_path)
    gold_rows = read_csv(gold_path)
    prediction_by_id = {row["document_id"]: row for row in predictions}
    joined: list[dict[str, str]] = []
    missing_predictions: list[str] = []
    invalid_labels: dict[str, str] = {}
    for row in gold_rows:
        document_id = str(row.get("document_id") or "")
        if document_id not in prediction_by_id:
            missing_predictions.append(document_id)
            continue
        label = str(row.get("gold_label") or "").strip().casefold()
        if label and label not in VALID_LABELS:
            invalid_labels[document_id] = label
        joined.append(
            {
                **prediction_by_id[document_id],
                "gold_label": label,
            }
        )
    labeled_rows = [row for row in joined if row["gold_label"] in VALID_LABELS]
    missing_gold_count = len(joined) - len(labeled_rows)
    deferred_rows = [row for row in labeled_rows if row["gold_label"] == "needs_review"]
    resolved_rows = [
        row for row in labeled_rows if row["gold_label"] in RESOLVED_LABELS
    ]
    status = (
        "EVALUATED"
        if not missing_gold_count and not invalid_labels
        else "NOT_EVALUATED"
    )
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": status,
        "scope": scope,
        "predictions_path": str(predictions_path.relative_to(ROOT)),
        "gold_path": str(gold_path.relative_to(ROOT)),
        "population_count": len(predictions),
        "gold_row_count": len(gold_rows),
        "joined_row_count": len(joined),
        "labeled_count": len(labeled_rows),
        "missing_gold_count": missing_gold_count,
        "deferred_needs_review_count": len(deferred_rows),
        "resolved_count_for_binary_metrics": len(resolved_rows),
        "gold_label_counts": dict(
            sorted(Counter(row["gold_label"] for row in labeled_rows).items())
        ),
        "invalid_labels": invalid_labels,
        "missing_predictions": missing_predictions,
        "metrics": None,
        "general_population_recall_allowed": scope == "full_corpus",
        "needs_review_policy": (
            "excluded from binary precision/recall; never auto-negative"
        ),
        "llm_calls": 0,
        "db_writes": 0,
        "reason": None,
    }
    if status != "EVALUATED":
        result["reason"] = (
            "Every row in the selected evaluation scope needs an explicit human "
            "Gold Label; missing/invalid labels are not inferred."
        )
    elif not resolved_rows:
        result["status"] = "NOT_EVALUATED"
        result["reason"] = (
            "No approved or irrelevant labels remain after deferring needs_review."
        )
    elif not any(row["gold_label"] == "approved" for row in resolved_rows) or not any(
        row["gold_label"] == "irrelevant" for row in resolved_rows
    ):
        result["status"] = "NOT_EVALUATED"
        result["reason"] = (
            "Both approved and irrelevant labels are required for binary metrics."
        )
    else:
        result["metrics"] = binary_metrics(resolved_rows)
        if scope == "sampled_review_set":
            result["reason"] = (
                "Metrics apply only to the explicitly labeled sampled review set; "
                "they are not exact recall for all 789 documents."
            )
    return result


def main() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument(
        "--scope",
        choices=("sampled_review_set", "full_corpus"),
        default="sampled_review_set",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    result = evaluate(args.predictions, args.gold, args.scope)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
