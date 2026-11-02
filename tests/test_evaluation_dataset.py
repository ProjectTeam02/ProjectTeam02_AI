import pytest

from app.dataset_pipeline.evaluation_dataset import (
    cohen_kappa,
    contingency,
    label_agreement_report,
    score,
)


def test_status_text_is_not_numeric_gold() -> None:
    assert score("완료") is None
    assert score("2") == 2
    assert score(" 1 ") == 1


def test_agreement_recomputes_bok_style_92_disagreements() -> None:
    rows = [
        {"source": "BOK", "label_a": 0, "label_b": 0},
        {"source": "BOK", "label_a": 1, "label_b": 2},
        {"source": "KDI", "label_a": 2, "label_b": None},
    ]
    report = label_agreement_report(rows)
    assert report["by_source"]["BOK"]["comparable_count"] == 2
    assert report["by_source"]["BOK"]["agree_count"] == 1
    assert report["by_source"]["BOK"]["disagree_count"] == 1
    assert report["human_inter_rater_agreement_status"].startswith("NOT_COMPUTED")


def test_confusion_and_kappa_are_stable_for_three_class_labels() -> None:
    rows = [
        {"label_a": 0, "label_b": 0},
        {"label_a": 1, "label_b": 1},
        {"label_a": 2, "label_b": 1},
    ]
    assert contingency(rows, "label_a", "label_b")["comparable_count"] == 3
    assert cohen_kappa(rows, "label_a", "label_b") == pytest.approx(0.5)
