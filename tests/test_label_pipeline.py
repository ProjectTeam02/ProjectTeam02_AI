# 파일 역할: 라벨 품질 검사와 목적별 평가 정책의 회귀 테스트입니다.
from __future__ import annotations

from pathlib import Path

import pytest

from app.dataset_pipeline.chunks import Chunk
from app.dataset_pipeline.evaluation import (
    positive_for_use,
    precision_recall_f1,
    validate_relevance_score,
)
from app.dataset_pipeline.keywords import (
    Chapter,
    classify_chunk_by_keywords,
    keyword_candidates,
)
from app.dataset_pipeline.labels import analyze_label_rows


def test_relevance_policy_is_separate_by_usage() -> None:
    # 문제 생성과 튜터 검색이 같은 임계값을 쓰지 않는지 확인합니다.
    assert positive_for_use(2, "question_generation") is True
    assert positive_for_use(1, "question_generation") is False
    assert positive_for_use(1, "tutor_retrieval") is True
    assert positive_for_use(0, "tutor_retrieval") is False


def test_relevance_score_rejects_out_of_range_values() -> None:
    # 관련도는 0·1·2 이외의 값이나 Boolean을 허용하지 않아야 합니다.
    with pytest.raises(ValueError):
        validate_relevance_score(3)
    with pytest.raises(ValueError):
        validate_relevance_score(True)


def test_metrics_are_only_calculated_from_explicit_gold_values() -> None:
    # 시스템 예측과 독립 골드 라벨의 조합으로만 평가 지표를 계산합니다.
    counts = {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert precision_recall_f1(counts) == {"precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_label_audit_finds_duplicates_and_manual_review_term() -> None:
    # 중복 ID와 지정 수동 검수 용어가 실제 검수 후보로 잡히는지 확인합니다.
    rows = [
        {
            "원문ID": "a",
            "표제어": "기준금리",
            "설명": "기준금리는 중앙은행의 정책금리다.",
            "출처": "BOK",
            "관련도": "1",
            "평가자A": "1",
            "평가자B": "2",
            "판정근거": "중앙은행의 정책금리",
        },
        {
            "원문ID": "a",
            "표제어": "기준금리",
            "설명": "기준금리는 중앙은행의 정책금리다.",
            "출처": "BOK",
            "관련도": "1",
            "평가자A": "1",
            "평가자B": "1",
            "판정근거": "중앙은행의 정책금리",
        },
    ]
    result = analyze_label_rows(rows, Path("라벨링.xlsx"))
    assert result["integrity"]["duplicate_ids"] == {"a": 2}
    assert result["label_consistency"]["disagreement_count"] == 1
    assert any(
        "specified_manual_review_term" in item["review_reason"]
        for item in result["manual_review_candidates"]
    )


def test_keyword_alias_and_synonym_are_candidate_signals_only() -> None:
    # 약어·영문명이 매칭되더라도 결과가 최종 관련도 판정이 아님을 확인합니다.
    chunk = Chunk(
        document_id="doc-1",
        chunk_id="chunk-1",
        source="TEST",
        title="Consumer Price Index",
        content="CPI는 소비자물가지수의 약어다.",
        source_url=None,
        source_locator=None,
        chunk_index=0,
        token_count=10,
        text_hash="hash",
        dataset_version="v1",
        source_review_status="UNKNOWN",
        license_status="UNCONFIRMED",
    )
    chapter = Chapter(
        chapter_id="inflation",
        chapter_name="물가와 인플레이션",
        chapter_definition="물가 측정",
        include_criteria="물가 측정 지표 설명",
        exclude_criteria="단순 언급",
        keywords=("소비자물가지수",),
        related_keywords=(),
        opposite_keywords=(),
        exclude_keywords=(),
        rubric_version="draft-v1",
        aliases=("CPI", "Consumer Price Index"),
    )
    result = classify_chunk_by_keywords(chunk, chapter)
    assert result["candidate"] is True
    assert {"alias", "core"}.issuperset(result["matched_keyword_types"])
    assert result["keyword_score_is_not_relevance"] is True


def test_duplicate_chunk_id_is_not_counted_twice() -> None:
    # JSON과 JSONL 중복 또는 재실행으로 같은 청크가 들어와도 중복 집계하지 않습니다.
    chunk = Chunk(
        document_id="doc-1",
        chunk_id="chunk-1",
        source="TEST",
        title="인플레이션",
        content="물가 상승을 설명한다.",
        source_url=None,
        source_locator=None,
        chunk_index=0,
        token_count=5,
        text_hash="hash",
        dataset_version="v1",
        source_review_status="UNKNOWN",
        license_status="UNCONFIRMED",
    )
    chapter = Chapter(
        chapter_id="inflation",
        chapter_name="물가와 인플레이션",
        chapter_definition="물가",
        include_criteria="정의",
        exclude_criteria="무관",
        keywords=("인플레이션",),
        related_keywords=(),
        opposite_keywords=(),
        exclude_keywords=(),
        rubric_version="draft-v1",
    )
    rows, summary = keyword_candidates([chunk, chunk], [chapter])
    assert len(rows) == 1
    assert summary["candidate_chunk_count"] == 1
