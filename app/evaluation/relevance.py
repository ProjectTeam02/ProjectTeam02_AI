"""Hybrid relevance classification interfaces and offline evaluation helpers.

Only the deterministic keyword classifier is executable without an approved
LLM call.  The LLM adapter is deliberately an interface so a missing provider
cannot silently turn into fabricated labels.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Protocol

from app.question_generation.dataset import select_c0704_candidates


class RelevanceClassifier(Protocol):
    version: str

    def classify(self, row: dict[str, Any], concept_code: str) -> dict[str, Any]: ...


@dataclass(frozen=True, slots=True)
class ClassificationMetrics:
    status: str
    tp: int = 0
    fp: int = 0
    fn: int = 0
    precision: float | None = None
    recall: float | None = None
    f1: float | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


class KeywordRelevanceClassifier:
    """Offline first-pass classifier; outputs remain PENDING for humans."""

    version = "keyword-v1"

    def classify(
        self, row: dict[str, Any], concept_code: str = "C0704"
    ) -> dict[str, Any]:
        candidates = select_c0704_candidates([row])
        if not candidates:
            return {
                "concept_code": concept_code,
                "document_id": row.get("document_id"),
                "chunk_id": row.get("chunk_id"),
                "relevance_score": 0.0,
                "classification_label": "EXCLUDE",
                "classification_reason": "개념 키워드가 발견되지 않음",
                "subtopic": None,
                "classifier_version": self.version,
                "review_status": "PENDING",
            }
        result = candidates[0]
        result["concept_code"] = concept_code
        result["classifier_version"] = self.version
        result["review_status"] = "PENDING"
        return result


class LLMRelevanceClassifier:
    """Explicitly non-operational until an approved callable is supplied."""

    version = "llm-dry-run-v1"

    def __init__(self, client=None):
        self.client = client

    def classify(
        self, row: dict[str, Any], concept_code: str = "C0704"
    ) -> dict[str, Any]:
        if self.client is None:
            raise RuntimeError(
                "LLM relevance classification is not configured; no model call was made"
            )
        result = self.client(row=row, concept_code=concept_code)
        if not isinstance(result, dict):
            raise ValueError("LLM classifier must return an object")
        result.setdefault("concept_code", concept_code)
        result.setdefault("document_id", row.get("document_id"))
        result.setdefault("chunk_id", row.get("chunk_id"))
        result.setdefault("classifier_version", self.version)
        result.setdefault("review_status", "PENDING")
        return result


def evaluate_classification(
    predictions: dict[str, str],
    gold_labels: dict[str, str] | None,
    positive_labels: set[str] | None = None,
) -> ClassificationMetrics:
    """Evaluate only supplied human gold labels; missing labels are not inferred."""
    if not gold_labels:
        return ClassificationMetrics(
            status="NOT_EVALUATED",
            reason=(
                "human gold labels are required; candidate labels are not ground truth"
            ),
        )
    positive = positive_labels or {"DIRECT", "INDIRECT"}
    keys = set(gold_labels)
    tp = sum(
        predictions.get(key) in positive and gold_labels[key] in positive
        for key in keys
    )
    fp = sum(
        predictions.get(key) in positive and gold_labels[key] not in positive
        for key in keys
    )
    fn = sum(
        predictions.get(key) not in positive and gold_labels[key] in positive
        for key in keys
    )
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ClassificationMetrics(
        status="EVALUATED",
        tp=tp,
        fp=fp,
        fn=fn,
        precision=precision,
        recall=recall,
        f1=f1,
    )
