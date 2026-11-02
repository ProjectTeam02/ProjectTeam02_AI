# 파일 역할: 챕터 관련도 라벨을 용도별 이진 평가 지표로 변환합니다.
"""Offline evaluation helpers for human-approved relevance labels.

The functions in this module deliberately refuse to call a prediction a gold
label.  Metrics are meaningful only after an independent human review set is
provided.
"""

from __future__ import annotations

from collections import Counter
from typing import Iterable

VALID_RELEVANCE_SCORES = {0, 1, 2}


def validate_relevance_score(value: object) -> int:
    """Validate and return an integer 0/1/2 relevance score."""
    if isinstance(value, bool):
        raise ValueError("boolean values are not valid relevance scores")
    try:
        score = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid relevance score: {value!r}") from exc
    if score not in VALID_RELEVANCE_SCORES or str(value).strip() != str(score):
        raise ValueError(
            f"relevance score must be one of {sorted(VALID_RELEVANCE_SCORES)}"
        )
    return score


def positive_for_use(score: int, usage: str) -> bool:
    """Apply the separate quiz and tutor policies to an approved label."""
    score = validate_relevance_score(score)
    if usage == "question_generation":
        return score == 2
    if usage == "tutor_retrieval":
        return score in {1, 2}
    raise ValueError("usage must be question_generation or tutor_retrieval")


def confusion_matrix(
    predictions: Iterable[bool], gold: Iterable[bool]
) -> dict[str, int]:
    """Return TP/FP/FN/TN for equal-length binary sequences."""
    counts = Counter()
    prediction_values = list(predictions)
    gold_values = list(gold)
    if len(prediction_values) != len(gold_values):
        raise ValueError("predictions and gold must have equal lengths")
    for predicted, actual in zip(prediction_values, gold_values):
        if predicted and actual:
            counts["tp"] += 1
        elif predicted and not actual:
            counts["fp"] += 1
        elif not predicted and actual:
            counts["fn"] += 1
        else:
            counts["tn"] += 1
    return {key: counts[key] for key in ("tp", "fp", "fn", "tn")}


def precision_recall_f1(matrix: dict[str, int]) -> dict[str, float]:
    """Calculate metrics from a human-reviewed confusion matrix."""
    tp, fp, fn = matrix["tp"], matrix["fp"], matrix["fn"]
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {"precision": precision, "recall": recall, "f1": f1}
