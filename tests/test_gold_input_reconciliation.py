from __future__ import annotations

import csv
from pathlib import Path

from scripts.reconcile_gold_inputs import run as reconcile_gold_inputs
from scripts.run_kdi_bok_evaluation import run_hybrid_predictions


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_reconciliation_excludes_legacy_mixed_templates(tmp_path: Path) -> None:
    queue_row = {"document_id": "kdi-1", "source_group": "KDI"}
    _write_rows(tmp_path / "queue.csv", [queue_row])
    _write_rows(tmp_path / "kdi.csv", [{"document_id": "bok-old", "source": "BOK"}])
    _write_rows(tmp_path / "bok.csv", [{"document_id": "bok-1", "source": "BOK"}])

    result = reconcile_gold_inputs(
        tmp_path / "queue.csv",
        tmp_path / "kdi.csv",
        tmp_path / "bok.csv",
        tmp_path / "result.json",
        tmp_path / "result.md",
    )

    assert result["status"] == "FAIL"
    assert result["mixing_prevented"] is True
    assert result["legacy_inputs"]["kdi_template"]["status"] == (
        "LEGACY_EXCLUDED_SOURCE_MISMATCH"
    )


def test_hybrid_separates_observed_and_missing_candidate_predictions() -> None:
    rows = [
        {"source": "KDI", "document_id": "negative", "title": "무관"},
        {"source": "BOK", "document_id": "observed", "title": "관측"},
        {"source": "KDI", "document_id": "missing", "title": "미관측"},
    ]
    keyword_rows = [
        {
            **row,
            "content_hash": row["document_id"],
            "keyword_candidate": row["document_id"] != "negative",
            "matched_keywords": [],
            "reference_label": None,
            "reference_label_provenance": "NONE",
        }
        for row in rows
    ]
    llm_rows = [
        {
            "document_id": "negative",
            "prediction_status": "NOT_EXECUTED",
            "predicted_label": None,
            "relevance_score": None,
        },
        {
            "document_id": "observed",
            "prediction_status": "PILOT_REUSED_PENDING",
            "predicted_label": 2,
            "relevance_score": 0.9,
        },
        {
            "document_id": "missing",
            "prediction_status": "NOT_EXECUTED",
            "predicted_label": None,
            "relevance_score": None,
        },
    ]

    result = run_hybrid_predictions(rows, keyword_rows, llm_rows)
    status_by_id = {row["document_id"]: row["prediction_status"] for row in result}

    assert status_by_id == {
        "negative": "COMPLETED_KEYWORD_NEGATIVE",
        "observed": "LLM_OBSERVED_PENDING_REVIEW",
        "missing": "NOT_EXECUTED_LLM_MISSING",
    }
    assert sum(row["predicted_label"] is not None for row in result) == 2
