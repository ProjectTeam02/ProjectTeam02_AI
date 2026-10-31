from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.evaluation.relevance import KeywordRelevanceClassifier, evaluate_classification
from app.ingestion.mentor_dataset import (
    inspect_terms_dataset,
    select_c0704_candidates,
    validate_curriculum,
)


def _row(document_id: str, term: str, source: str = "BOK") -> dict:
    content = f"{term}의 정의와 물가상승률 설명"
    return {
        "document_id": document_id,
        "source_id": f"{source}-1",
        "source_type": source,
        "title": term,
        "term": term,
        "definition": content,
        "content": content,
        "content_hash": hashlib.sha256(content.encode()).hexdigest(),
        "document_version": "1",
        "source_url": "https://example.test/source",
        "review_status": "approved",
        "license": "review-required",
        "knowledge_scope": "global",
    }


def test_missing_mentor_files_are_reported_without_substitution(tmp_path: Path) -> None:
    report = inspect_terms_dataset(
        tmp_path / "approved.jsonl", tmp_path / "review.jsonl"
    )
    assert report.status == "NOT_AVAILABLE"
    assert report.approved_count == 0


def test_terms_inventory_detects_hashes_and_source_counts(tmp_path: Path) -> None:
    approved = tmp_path / "terms_approved.jsonl"
    review = tmp_path / "terms_needs_review.jsonl"
    approved.write_text(
        json.dumps(_row("bok-1", "인플레이션")) + "\n", encoding="utf-8"
    )
    review_row = _row("kdi-1", "디플레이션", "KDI")
    review_row["review_status"] = "needs_review"
    review.write_text(json.dumps(review_row) + "\n", encoding="utf-8")
    report = inspect_terms_dataset(approved, review)
    assert report.status == "VALID_WITH_EXPECTATION_MISMATCH"
    assert report.source_counts == {"BOK": 1}
    assert report.review_source_counts == {"KDI": 1}
    assert report.content_hash_mismatches == ()


def test_c0704_selection_keeps_pending_and_excludes_ira_false_positive() -> None:
    unrelated = _row("bok-3", "금융시장")
    unrelated["content"] = "금융시장과 유동성에 대한 정의"
    unrelated["definition"] = unrelated["content"]
    ira = _row("bok-2", "인플레이션감축법(IRA)")
    ira["content"] = "인플레이션감축법(IRA)에 대한 법률 설명"
    ira["definition"] = ira["content"]
    rows = [
        _row("bok-1", "인플레이션"),
        ira,
        unrelated,
    ]
    candidates = select_c0704_candidates(rows)
    assert {row["document_id"] for row in candidates} == {"bok-1", "bok-2"}
    assert all(row["review_status"] == "PENDING" for row in candidates)
    ira = next(row for row in candidates if row["document_id"] == "bok-2")
    assert ira["classification_label"] == "EXCLUDE"
    assert ira["chunk_id"] is None


def test_keyword_classifier_and_gold_label_metrics_are_explicit() -> None:
    result = KeywordRelevanceClassifier().classify(_row("bok-1", "인플레이션"))
    assert result["classification_label"] == "DIRECT"
    assert result["review_status"] == "PENDING"
    not_evaluated = evaluate_classification({"bok-1": "DIRECT"}, None)
    assert not_evaluated.status == "NOT_EVALUATED"
    measured = evaluate_classification(
        {"bok-1": "DIRECT", "bok-2": "EXCLUDE"},
        {"bok-1": "DIRECT", "bok-2": "EXCLUDE"},
    )
    assert measured.precision == 1.0
    assert measured.recall == 1.0
    assert measured.f1 == 1.0


def test_curriculum_validator_checks_prerequisite_direction(tmp_path: Path) -> None:
    path = tmp_path / "curriculum_full.json"
    path.write_text(
        json.dumps(
            {
                "meta": {"status": "DRAFT"},
                "regions": [
                    {
                        "region_id": "R07",
                        "stages": [
                            {
                                "stage_id": "R07_S04",
                                "concept_id": "C0704",
                                "question_blueprint": [{"type": "compare"}],
                            }
                        ],
                        "boss": {"stage_id": "R07_BOSS", "stage_type": "BOSS"},
                    }
                ],
                "concepts": [
                    {"concept_id": "C0701", "app_concept_id": "app-1"},
                    {"concept_id": "C0704", "app_concept_id": "app-4"},
                ],
                "edges": [{"source": "C0701", "target": "C0704", "type": "required"}],
                "topic_unlock_policy": {"status": "NOT_FINALIZED", "rules": []},
            }
        ),
        encoding="utf-8",
    )
    report = validate_curriculum(path)
    assert report.status == "VALID"
    assert report.region_count == 1
    assert report.concept_count == 2
    assert report.required_edge_count == 1
    assert report.draft_status == "DRAFT"
    assert report.unlock_policy_status == "NOT_FINALIZED"
