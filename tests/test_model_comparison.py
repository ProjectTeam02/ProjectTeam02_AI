from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.config import Settings
from app.model_comparison.catalog import MODEL_SPECS
from app.model_comparison.contracts import ComparisonCase, ComparisonResult
from app.model_comparison.io import JsonlResultStore, load_cases, write_template
from app.model_comparison.runner import ModelComparisonRunner
from app.rag.retrieval.types import RetrievedDocument


def comparison_case() -> ComparisonCase:
    return ComparisonCase(
        case_id="TEST-001",
        question="GDP가 뭐야?",
        history=[{"role": "user", "content": "경제 지표를 공부하고 있어."}],
        corpus=[
            RetrievedDocument(
                content=(
                    "GDP는 일정 기간 한 나라 안에서 생산된 최종 재화와 서비스의 가치다."
                ),
                source="approved-test",
                document_id="DOC-1",
                chunk_id="DOC-1:1",
                title="GDP 기초",
            )
        ],
    )


def test_catalog_contains_requested_models_in_order():
    assert [spec.model_id for spec in MODEL_SPECS] == [
        "google/gemini-3.1-flash-lite",
        "google/gemini-3-flash-preview",
        "openai/gpt-5.4-mini",
        "qwen/qwen3.5-flash-02-23",
        "anthropic/claude-haiku-4.5",
    ]
    assert all(spec.supports_text and spec.supports_multiturn for spec in MODEL_SPECS)


@pytest.mark.asyncio
async def test_mock_runner_uses_same_rag_path_and_writes_usage(tmp_path: Path):
    output = tmp_path / "results.jsonl"
    runner = ModelComparisonRunner(
        settings=Settings(_env_file=None), model_specs=MODEL_SPECS[:2]
    )

    results = await runner.run([comparison_case()], str(output))

    assert len(results) == 2
    assert {result.status for result in results} == {"mock"}
    assert all(result.mode == "mock" for result in results)
    assert all(result.usage["input_tokens"] == 32 for result in results)
    assert all(result.usage["output_tokens"] == 18 for result in results)
    assert all(result.prompt_version.startswith("tutor-v2") for result in results)
    assert len(output.read_text(encoding="utf-8").splitlines()) == 2


@pytest.mark.asyncio
async def test_resume_skips_completed_rows_but_keeps_live_and_mock_separate(
    tmp_path: Path,
):
    output = tmp_path / "results.jsonl"
    runner = ModelComparisonRunner(
        settings=Settings(_env_file=None), model_specs=MODEL_SPECS[:1]
    )
    case = comparison_case()

    first = await runner.run([case], str(output))
    second = await runner.run([case], str(output))
    live_mode = await runner.run([case], str(output), execute=True)

    assert len(first) == 1
    assert second == []
    assert len(live_mode) == 1
    rows = [
        json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
    ]
    assert {(row["mode"], row["status"]) for row in rows} == {
        ("mock", "mock"),
        ("live", "error"),
    }


def test_jsonl_store_restarts_from_last_success(tmp_path: Path):
    output = tmp_path / "results.jsonl"
    store = JsonlResultStore(output)
    store.append(
        ComparisonResult(
            case_id="A",
            model_id="model-a",
            mode="live",
            status="ok",
            latency_ms=10,
            input_hash="hash",
            prompt_version="prompt",
        )
    )
    store.append(
        ComparisonResult(
            case_id="B",
            model_id="model-a",
            mode="live",
            status="error",
            latency_ms=10,
            input_hash="hash",
            prompt_version="prompt",
            error_type="GenerationError",
            error_code="generation_error",
        )
    )

    restarted = JsonlResultStore(output)
    assert restarted.is_completed("A", "model-a", "live")
    assert not restarted.is_completed("B", "model-a", "live")


def test_load_cases_and_template_are_jsonl(tmp_path: Path):
    template = tmp_path / "template.jsonl"
    write_template(template, count=2)
    payloads = [
        json.loads(line) for line in template.read_text(encoding="utf-8").splitlines()
    ]
    assert len(payloads) == 2
    assert len(load_cases(template)) == 2


def test_load_cases_accepts_tutor_dataset_public_shape(tmp_path: Path):
    path = tmp_path / "tutor_test_100.jsonl"
    path.write_text(
        json.dumps(
            {
                "caseId": "TUTOR-001",
                "studentQuestion": "기준금리는 무엇인가요?",
                "conversationHistory": [
                    {
                        "sequenceNo": 1,
                        "role": "USER",
                        "content": "금리를 공부하고 있어요.",
                    }
                ],
                "approvedEvidence": [],
                "expectedConcepts": ["기준금리"],
                "expectedTeachingBehavior": ["cite_source"],
                "goldStatus": "PENDING_REVIEW",
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )

    cases = load_cases(path)

    assert len(cases) == 1
    assert cases[0].case_id == "TUTOR-001"
    assert cases[0].question == "기준금리는 무엇인가요?"
    assert cases[0].history[0]["role"] == "user"
    assert cases[0].corpus == []
