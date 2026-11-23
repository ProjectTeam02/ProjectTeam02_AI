from __future__ import annotations

import asyncio

import pytest

from app.core.config import Settings
from app.evaluation.model_selection import analyze_model_selection
from app.rag.generation.fallback_llm import FallbackLLM


class Response:
    def __init__(self, text: str):
        self.text = text


class FakeLLM:
    def __init__(self, result=None, error=None, delay=0):
        self.result = result
        self.error = error
        self.delay = delay
        self.calls = 0

    async def acomplete(self, prompt):
        del prompt
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error:
            raise self.error
        return self.result


def test_tutor_and_question_generation_model_overrides_are_independent():
    settings = Settings(
        _env_file=None,
        llm_provider="openrouter",
        llm_model="legacy/model",
        tutor_llm_model="tutor/model",
        question_generation_llm_model="question/model",
    )

    assert settings.for_tutor().llm_model == "tutor/model"
    assert settings.for_question_generation().llm_model == "question/model"
    assert settings.llm_model == "legacy/model"


def test_fallback_uses_primary_response_without_calling_fallback():
    primary = FakeLLM(result=Response("primary"))
    fallback = FakeLLM(result=Response("fallback"))
    llm = FallbackLLM(
        primary,
        fallback,
        primary_model_id="primary/model",
        fallback_model_id="fallback/model",
    )

    response = asyncio.run(llm.acomplete("prompt"))

    assert response.text == "primary"
    assert primary.calls == 1
    assert fallback.calls == 0
    assert llm.model_id == "primary/model"


def test_fallback_uses_secondary_after_primary_timeout():
    primary = FakeLLM(delay=0.05)
    fallback = FakeLLM(result=Response("fallback"))
    llm = FallbackLLM(
        primary,
        fallback,
        primary_model_id="primary/model",
        fallback_model_id="fallback/model",
        attempt_timeout_seconds=0.001,
    )

    response = asyncio.run(llm.acomplete("prompt"))

    assert response.text == "fallback"
    assert primary.calls == 1
    assert fallback.calls == 1
    assert llm.model_id == "fallback/model"


def test_model_selection_blocks_without_live_and_review_evidence():
    models = [
        "google/gemini-3.1-flash-lite",
        "google/gemini-3-flash-preview",
        "openai/gpt-5.4-mini",
        "qwen/qwen3.5-flash-02-23",
        "anthropic/claude-haiku-4.5",
    ]
    record = analyze_model_selection(
        dataset_rows=[{"caseId": "case-1", "goldStatus": "PENDING_REVIEW"}],
        comparison_rows=[
            {
                "model_id": model,
                "mode": "mock",
                "status": "ok",
                "latency_ms": 1,
            }
            for model in models
        ],
        quality_rows=[
            {
                "modelId": model,
                "evaluationStatus": "NOT_EVALUATED_UNREVIEWED_GOLD",
            }
            for model in models
        ],
        human_review_rows=[],
        context_rows=[],
    )

    assert record["decisionStatus"] == "NOT_READY"
    assert record["primaryModel"] is None
    assert record["fallbackModel"] is None
    assert not any(record["gates"].values())
    assert "5개 모델의 실제 live 비용·TTFT·p50/p95·성공률" in record[
        "missingEvidence"
    ]


@pytest.mark.parametrize("provider", ["openrouter", "openai"])
def test_legacy_model_remains_default_until_tutor_override_is_explicit(provider):
    settings = Settings(_env_file=None, llm_provider=provider, llm_model="legacy/model")
    assert settings.for_tutor().llm_provider == provider
    assert settings.for_tutor().llm_model == "legacy/model"
