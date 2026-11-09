# 파일 역할: Excel 라벨 기반 정밀도 파이프라인의 목적별 평가 계약을 검증합니다.
from __future__ import annotations

from app.dataset_pipeline.labels import analyze_label_rows
from scripts.rebuild_precision_pipeline import _keyword_metrics, _policy_metrics


def test_excel_column_aliases_support_reviewer_a_b_and_gold() -> None:
    # 실제 Excel 열 이름을 축약 별칭으로 바꾸지 않아도 정확히 연결되는지 확인합니다.
    rows = [
        {
            "원문ID": "doc-1",
            "용어": "인플레이션",
            "설명": "인플레이션은 물가가 지속적으로 상승하는 현상이다.",
            "출처": "KDI",
            "원문 위치": "https://example.test/doc-1",
            "글자수": "30",
            "자료 품질": "정상",
            "관련도 A": "2",
            "관련도 B": "1",
            "확정 골드": "2",
            "문제 생성 적합": "적합",
            "튜터 검색 적합": "적합",
            "판정 근거": "인플레이션 개념을 설명함",
        }
    ]
    result = analyze_label_rows(rows, __import__("pathlib").Path("라벨링.xlsx"))
    assert result["detected_columns"]["reviewer_a"] == "관련도 A"
    assert result["detected_columns"]["reviewer_b"] == "관련도 B"
    assert result["detected_columns"]["gold"] == "확정 골드"
    assert result["label_consistency"]["reviewer_b_filled_count"] == 1


def test_precision_pipeline_keeps_question_and_tutor_policies_separate() -> None:
    # 동일한 후보라도 문제 생성과 튜터 검색의 양성 기준이 다르게 계산되어야 합니다.
    records = [
        {"quiz_suitable": True, "tutor_suitable": True, "gold_score": 2},
        {"quiz_suitable": False, "tutor_suitable": True, "gold_score": 1},
        {"quiz_suitable": False, "tutor_suitable": False, "gold_score": 0},
    ]
    quiz = _policy_metrics(records, "quiz_suitable", "question_generation")
    tutor = _policy_metrics(records, "tutor_suitable", "tutor_retrieval")
    assert quiz["metrics"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert tutor["metrics"] == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_keyword_metrics_reports_recall_loss_without_inventing_labels() -> None:
    # 키워드가 일부 양성만 찾으면 높은 정밀도와 낮은 재현율을 동시에 보여야 합니다.
    rows = [
        {"candidate": True, "gold_score": 2},
        {"candidate": False, "gold_score": 2},
        {"candidate": False, "gold_score": 0},
    ]
    result = _keyword_metrics(rows, "question_generation")
    assert result["candidate_count"] == 1
    assert result["metrics"]["precision"] == 1.0
    assert result["metrics"]["recall"] == 0.5
