# 파일 역할: 프로젝트 기능과 데이터 계약을 자동으로 검증하는 테스트 코드입니다.
from __future__ import annotations

import pytest

from app.dataset_pipeline.chunks import chunk_document
from app.dataset_pipeline.classification import validate_classification_output
from app.dataset_pipeline.io import NormalizedDocument, load_corpus
from app.dataset_pipeline.keywords import Chapter, classify_chunk_by_keywords
from app.dataset_pipeline.tokenizer import ExactTokenizer


def _document(
    content: str = "인플레이션은 물가가 지속적으로 상승하는 현상이다.",
) -> NormalizedDocument:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return NormalizedDocument(
        source="TEST",
        document_id="test-1",
        title="테스트 용어",
        content=content,
        source_url="https://example.test/source",
        source_locator="page=1",
        source_name="test",
        source_version="v1",
        source_review_status="UNKNOWN",
        license_status="UNCONFIRMED",
        text_hash="hash",
        related_terms=(),
        raw_file="test.jsonl",
    )


def test_chunk_keeps_short_definition_and_lineage() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    tokenizer = ExactTokenizer()
    chunks = chunk_document(_document(), tokenizer, "dataset-v1", 700, 100)
    assert len(chunks) == 1
    assert chunks[0].document_id == "test-1"
    assert chunks[0].dataset_version == "dataset-v1"
    assert chunks[0].token_count == tokenizer.count(chunks[0].content)


def test_long_text_is_split_by_token_limit() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    tokenizer = ExactTokenizer()
    chunks = chunk_document(
        _document("물가 상승과 경제 정책. " * 500), tokenizer, "v1", 100, 10
    )
    assert len(chunks) > 1
    assert all(chunk.token_count <= 100 for chunk in chunks)
    assert all(chunk.chunk_id.startswith("TEST:test-1:chunk-") for chunk in chunks)


def test_keyword_result_is_pending_candidate_not_approval() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    tokenizer = ExactTokenizer()
    base = chunk_document(_document(), tokenizer, "v1")[0]
    chapter = Chapter(
        chapter_id="inflation",
        chapter_name="물가와 인플레이션",
        chapter_definition="물가와 물가상승률",
        include_criteria="정의",
        exclude_criteria="무관한 고유명사",
        keywords=("인플레이션",),
        related_keywords=(),
        opposite_keywords=(),
        exclude_keywords=(),
        rubric_version="v1",
    )
    result = classify_chunk_by_keywords(base, chapter)
    assert result["candidate"] is True
    assert result["review_status"] == "PENDING"
    assert result["keyword_match_score"] != 1.0


def test_classification_output_validates_lineage_and_score() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    value = {
        "chunk_id": "c1",
        "chapter_id": "inflation",
        "relevance_score": 0.92,
        "reason": "물가 상승을 정의함",
        "subtopics": ["물가 상승"],
        "evidence_span": "물가가 지속적으로 상승",
        "quiz_candidate": True,
        "needs_review": True,
    }
    result = validate_classification_output(value, "c1", "inflation")
    assert result["review_status"] == "PENDING"


def test_local_corpus_counts_current_mirrors_once() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    dataset_files = list(__import__("pathlib").Path("data").rglob("*terms*"))
    if not dataset_files:
        pytest.skip("로컬 원본 데이터가 없어 통합 데이터셋 검사를 건너뜁니다.")
    documents, inventory = load_corpus(__import__("pathlib").Path("data"))
    assert inventory["file_count"] == 4
    assert inventory["document_count"] == len(documents)
    assert inventory["document_count_by_source"] == {"BOK": 789, "KDI": 2750}
    assert all(
        item["same_id_count"] == item["canonical_records"]
        for item in inventory["duplicate_audit"]
    )
