from __future__ import annotations

from scripts.generate_model_evaluation_reports import _model_result


def test_report_keeps_mock_and_unreviewed_gold_out_of_final_scores():
    result = _model_result(
        "model/test",
        [
            {
                "model_id": "model/test",
                "mode": "mock",
                "status": "no_evidence",
            }
        ],
        [
            {
                "modelId": "model/test",
                "evaluationStatus": "NOT_EVALUATED_UNREVIEWED_GOLD",
            }
        ],
        None,
    )

    assert result["attempts"] == {
        "mock": 1,
        "interim": 0,
        "live": 0,
        "liveSuccessful": 0,
        "liveFailed": 0,
    }
    assert result["quality"]["goldGateBlocked"] == 1
    assert result["scores"] == {
        "educationQuality60": None,
        "operationsEfficiency40": None,
        "total100": None,
        "rank": None,
    }
