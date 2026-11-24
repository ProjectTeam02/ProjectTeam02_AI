from __future__ import annotations

import pytest

from app.model_comparison.runner import (
    ComparisonBudget,
    EvaluationBudgetExceeded,
)


def test_comparison_budget_stops_after_explicit_call_limit():
    budget = ComparisonBudget(max_calls=1)
    budget.reserve_call()
    with pytest.raises(EvaluationBudgetExceeded):
        budget.reserve_call()


def test_comparison_budget_tracks_estimated_cost():
    budget = ComparisonBudget(max_cost_usd=0.10)
    budget.record_cost(0.04)
    assert not budget.exhausted
    budget.record_cost(0.06)
    assert budget.exhausted

