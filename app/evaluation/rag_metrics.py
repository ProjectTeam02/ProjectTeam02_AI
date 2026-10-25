from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    recall_at_k: float
    mrr: float
    evaluated_queries: int


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    hits = relevant_ids.intersection(retrieved_ids[:k])
    return len(hits) / len(relevant_ids)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    for rank, document_id in enumerate(retrieved_ids, start=1):
        if document_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def evaluate_retrieval(
    cases: list[tuple[list[str], set[str]]], k: int = 5
) -> RetrievalEvaluation:
    if not cases:
        return RetrievalEvaluation(0.0, 0.0, 0)
    return RetrievalEvaluation(
        recall_at_k=mean(
            recall_at_k(retrieved, relevant, k) for retrieved, relevant in cases
        ),
        mrr=mean(reciprocal_rank(retrieved, relevant) for retrieved, relevant in cases),
        evaluated_queries=len(cases),
    )


def compare_runs(
    single_turn: list[tuple[list[str], set[str]]],
    multi_turn: list[tuple[list[str], set[str]]],
    k: int = 5,
) -> dict[str, RetrievalEvaluation]:
    """Compare two retrieval runs against the exact same relevance labels."""
    if len(single_turn) != len(multi_turn):
        raise ValueError(
            "single-turn and multi-turn runs must contain the same query count"
        )
    return {
        "single_turn": evaluate_retrieval(single_turn, k),
        "multi_turn": evaluate_retrieval(multi_turn, k),
    }
