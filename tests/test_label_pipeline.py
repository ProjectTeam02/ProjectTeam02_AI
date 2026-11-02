# 파일 역할: 라벨 품질 검사와 목적별 평가 정책의 회귀 테스트입니다.
from __future__ import annotations

from pathlib import Path

import pytest

from app.dataset_pipeline.chunks import Chunk
from app.dataset_pipeline.evaluation import (
    confusion_matrix,
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
    assert positive_for_use(2, "question_generation") is True
    assert positive_for_use(1, "question_generation") is False
    assert positive_for_use(1, "tutor_retrieval") is True
    assert positive_for_use(0, "tutor_retrieval") is False


def test_relevance_score_rejects_out_of_range_values() -> None:
    with pytest.raises(ValueError):
        validate_relevance_score(3)
    with pytest.raises(ValueError):
        validate_relevance_score(True)


def test_metrics_are_only_calculated_from_explicit_gold_values() -> None:
    matrix = confusion_matrix([True, True, False, False], [True, False, True, False])
    assert matrix == {"tp": 1, "fp": 1, "fn": 1, "tn": 1}
    assert precision_recall_f1(matrix) == {"precision": 0.5, "recall": 0.5, "f1": 0.5}


def test_label_audit_finds_duplicates_and_manual_review_term() -> None:
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
