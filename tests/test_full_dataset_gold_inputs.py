from app.dataset_pipeline.chunks import Chunk
from app.dataset_pipeline.io import NormalizedDocument
from scripts.assemble_independent_gold import _ready_test_row, _to_gold_row
from scripts.validate_full_dataset_gold_inputs import (
    _empty_gold_fields,
    _review_row,
    _split_for_review,
    validate_dataset,
)


def _document(document_id: str = "doc-1", source_url: str | None = None):
    return NormalizedDocument(
        source="BOK",
        document_id=document_id,
        title="물가",
        content="물가와 인플레이션을 설명하는 원문입니다.",
        source_url=source_url,
        source_locator="printed_page=1",
        source_name="한국은행",
        source_version="2026",
        source_review_status="UNKNOWN",
        license_status="UNCONFIRMED",
        text_hash=f"hash-{document_id}",
        related_terms=(),
        raw_file="data/bok_terms_2026_rag.jsonl",
    )


def _chunk(document: NormalizedDocument, index: int = 0):
    return Chunk(
        document_id=document.document_id,
        chunk_id=f"BOK:{document.document_id}:chunk-{index:04d}",
        source=document.source,
        title=document.title,
        content=document.content,
        source_url=document.source_url,
        source_locator=document.source_locator,
        chunk_index=index,
        token_count=10,
        text_hash=document.text_hash,
        dataset_version="dataset-v1",
        source_review_status=document.source_review_status,
        license_status=document.license_status,
    )


def test_review_fields_start_blank_and_pending() -> None:
    fields = _empty_gold_fields()
    assert fields["relevance_a"] == ""
    assert fields["relevance_b"] == ""
    assert fields["final_gold"] == ""
    assert fields["review_status"] == "PENDING"
    assert fields["gold_set_status"] == "PENDING_INDEPENDENT_REVIEW"


def test_review_split_is_reproducible_and_hash_based() -> None:
    first = _split_for_review("BOK", "doc-1", "same-hash")
    second = _split_for_review("BOK", "doc-1", "same-hash")
    assert first == second


def test_review_row_preserves_lineage_without_fabricating_url() -> None:
    document = _document()
    row = _review_row(document, _chunk(document), "dataset-v1", "random_non_candidate")
    assert row["document_id"] == "doc-1"
    assert row["chunk_id"] == "BOK:doc-1:chunk-0000"
    assert row["source_url"] == ""
    assert row["final_gold"] == ""
    assert row["review_status"] == "PENDING"


def test_validation_reports_quality_and_lineage_issues() -> None:
    first = _document("doc-1")
    second = _document("doc-2")
    chunks = [_chunk(first), _chunk(second)]
    result = validate_dataset(
        [first, second],
        chunks,
        max_tokens=700,
        token_counts={"doc-1": 10, "doc-2": 30},
    )
    assert result["quality_issues"]["bok_source_url_missing"]["count"] == 2
    assert result["quality_issues"]["under_20_tokens"]["count"] == 1
    assert (
        result["quality_issues"]["duplicate_content_hash_within_source"]["count"] == 0
    )
    assert result["lineage"]["missing_document_links"] == []


def test_pending_review_cannot_be_converted_to_gold() -> None:
    row = {
        "final_gold": "",
        "review_status": "PENDING",
        "gold_set_status": "PENDING_INDEPENDENT_REVIEW",
        "content_hash": "hash-1",
        "review_mode": "",
        "reviewer_count": "",
        "evidence_quote": "",
        "reason": "",
    }
    assert _ready_test_row(row)


def test_approved_template_maps_to_comparison_contract() -> None:
    row = {
        "source": "BOK",
        "final_gold": "2",
        "review_status": "APPROVED",
        "gold_set_status": "INDEPENDENT_APPROVED",
        "content_hash": "hash-1",
        "review_mode": "ADJUDICATED_CONSENSUS",
        "reviewer_count": "2",
        "evidence_quote": "원문 근거",
        "reason": "챕터 기준에 직접 부합",
    }
    assert _ready_test_row(row) == []
    mapped = _to_gold_row(row)
    assert mapped["source_group"] == "BOK"
    assert mapped["gold_score"] == "2"
