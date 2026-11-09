# 파일 역할: 검색 및 데이터 선별 결과의 평가 지표를 계산합니다.
from __future__ import annotations

from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True, slots=True)
class RetrievalEvaluation:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    recall_at_k: float
    mrr: float
    evaluated_queries: int


def recall_at_k(retrieved_ids: list[str], relevant_ids: set[str], k: int) -> float:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    hits = relevant_ids.intersection(retrieved_ids[:k])
    return len(hits) / len(relevant_ids)


def reciprocal_rank(retrieved_ids: list[str], relevant_ids: set[str]) -> float:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if not relevant_ids:
        raise ValueError("relevant_ids must not be empty")
    for rank, document_id in enumerate(retrieved_ids, start=1):
        if document_id in relevant_ids:
            return 1.0 / rank
    return 0.0


def evaluate_retrieval(
    cases: list[tuple[list[str], set[str]]], k: int = 5
) -> RetrievalEvaluation:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
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
