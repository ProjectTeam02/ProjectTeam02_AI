import csv

from scripts.compare_precision_methods import (
    _binary_metrics,
    _independent_gold_status,
    _threshold_prediction,
)


def _write_gold(path, rows):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "document_id",
                "content_hash",
                "source_group",
                "split",
                "gold_score",
                "gold_set_status",
                "review_status",
                "reviewer_count",
                "review_mode",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)


def test_missing_gold_set_is_not_ready(tmp_path) -> None:
    result = _independent_gold_status(tmp_path / "missing.csv")
    assert result["status"] == "MISSING"


def test_gold_set_requires_independent_approved_marker(tmp_path) -> None:
    path = tmp_path / "gold.csv"
    _write_gold(
        path,
        [
            {
                "document_id": "doc-1",
                "content_hash": "hash-1",
                "source_group": "KDI",
                "split": "test",
                "gold_score": "2",
                "gold_set_status": "INDEPENDENT_APPROVED",
                "review_status": "APPROVED",
                "reviewer_count": "2",
                "review_mode": "ADJUDICATED_CONSENSUS",
            }
        ],
    )
    result = _independent_gold_status(path)
    assert result["status"] == "READY"
    assert result["valid_row_count"] == 1


def test_gold_status_evaluates_only_approved_test_split(tmp_path) -> None:
    path = tmp_path / "gold.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "document_id",
                "content_hash",
                "source_group",
                "split",
                "gold_score",
                "gold_set_status",
                "review_status",
                "reviewer_count",
                "review_mode",
            ],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "document_id": "dev-1",
                    "content_hash": "hash-dev",
                    "source_group": "KDI",
                    "split": "development",
                    "gold_score": "",
                    "gold_set_status": "PENDING_INDEPENDENT_REVIEW",
                    "review_status": "PENDING",
                    "reviewer_count": "",
                    "review_mode": "",
                },
                {
                    "document_id": "test-1",
                    "content_hash": "hash-test",
                    "source_group": "BOK",
                    "split": "test",
                    "gold_score": "2",
                    "gold_set_status": "INDEPENDENT_APPROVED",
                    "review_status": "APPROVED",
                    "reviewer_count": "2",
                    "review_mode": "ADJUDICATED_CONSENSUS",
                },
            ]
        )
    result = _independent_gold_status(path)
    assert result["status"] == "READY"
    assert result["evaluation_row_count"] == 1
    assert result["rows"][0]["document_id"] == "test-1"


def test_gold_metrics_use_separate_quiz_and_tutor_policies() -> None:
    predictions = {"doc-1": True, "doc-2": False, "doc-3": True}
    gold = {"doc-1": 2, "doc-2": 1, "doc-3": 0}
    quiz = _binary_metrics(predictions, gold, "question_generation")
    tutor = _binary_metrics(predictions, gold, "tutor_retrieval")
    assert quiz["counts"] == {"tp": 1, "fp": 1, "fn": 0, "tn": 1}
    assert tutor["counts"] == {"tp": 1, "fp": 1, "fn": 1, "tn": 0}


def test_threshold_prediction_does_not_auto_approve_results() -> None:
    results = {
        "doc-1": {"relevance_score": 0.8, "review_status": "PENDING"},
        "doc-2": {"relevance_score": 0.4, "review_status": "PENDING"},
    }
    predictions = _threshold_prediction(results, 0.7)
    assert predictions == {"doc-1": True, "doc-2": False}
    assert all(row["review_status"] == "PENDING" for row in results.values())


def test_missing_predictions_block_final_metrics() -> None:
    result = _binary_metrics(
        {"doc-1": True},
        {"doc-1": 2, "doc-2": 0},
        "question_generation",
    )
    assert result["status"] == "NOT_EVALUATED_INCOMPLETE_PREDICTIONS"
    assert result["metrics"] is None
    assert result["missing_prediction_ids"] == ["doc-2"]
