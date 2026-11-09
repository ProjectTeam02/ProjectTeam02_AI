from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.dataset_pipeline.chunks import Chunk
from app.dataset_pipeline.keywords import Chapter
from app.dataset_pipeline.tokenizer import ExactTokenizer
from scripts import precision_llm_pilot


def _sample_rows(*_args) -> tuple[list[dict], Chapter, ExactTokenizer, Path]:
    # 실제 Excel 없이도 파일럿의 dry-run·응답 검증 흐름을 테스트합니다.
    tokenizer = ExactTokenizer("gpt-4o-mini")
    chapter = Chapter(
        chapter_id="inflation",
        chapter_name="물가와 인플레이션",
        chapter_definition="물가와 인플레이션의 개념",
        include_criteria="개념과 측정 설명",
        exclude_criteria="단순 언급",
        keywords=("인플레이션",),
        related_keywords=(),
        opposite_keywords=(),
        exclude_keywords=(),
        rubric_version="test-v1",
    )
    chunks = []
    for index, content in enumerate(
        [
            "인플레이션은 물가가 지속적으로 상승하는 현상이다.",
            "이 문서는 인플레이션과 무관한 일반 설명이다.",
        ]
    ):
        chunks.append(
            {
                "record": {"document_id": f"doc-{index}"},
                "chunk": Chunk(
                    document_id=f"doc-{index}",
                    chunk_id=f"chunk-{index}",
                    source="TEST",
                    title=f"제목 {index}",
                    content=content,
                    source_url=None,
                    source_locator=None,
                    chunk_index=0,
                    token_count=tokenizer.count(content),
                    text_hash=f"hash-{index}",
                    dataset_version="test",
                    source_review_status="정상",
                    license_status="UNCONFIRMED",
                ),
                "keyword_candidate": index == 0,
                "matched_keywords": ["인플레이션"] if index == 0 else [],
                "sampling_method": "test",
            }
        )
    return chunks, chapter, tokenizer, Path("test.xlsx")


def test_json_object_accepts_markdown_wrapped_response() -> None:
    # 모델이 JSON을 Markdown 코드 블록으로 감싸도 결과를 읽어야 합니다.
    result = precision_llm_pilot._json_object('```json\n{"score": 1}\n```')
    assert result == {"score": 1}


def test_pilot_dry_run_makes_zero_calls(monkeypatch, tmp_path) -> None:
    # 기본 모드에서는 API 키가 있어도 외부 호출이 발생하지 않아야 합니다.
    monkeypatch.setattr(precision_llm_pilot, "_load_experiment_rows", _sample_rows)
    output = tmp_path / "pilot.jsonl"
    result = precision_llm_pilot.run(output_path=output, sample_size=2, execute=False)
    assert result["llm_calls"] == 0
    assert result["status"] == "DRY_RUN_ONLY_NO_LLM_CALL"
    rows = [json.loads(line) for line in output.read_text().splitlines()]
    assert len(rows) == 2
    assert all(row["status"] == "DRY_RUN_NOT_CALLED" for row in rows)


def test_pilot_validates_fake_llm_response(monkeypatch, tmp_path) -> None:
    # 실제 API 대신 가짜 응답을 넣어 JSON·근거·메타데이터 저장을 검증합니다.
    rows, chapter, tokenizer, workbook = _sample_rows()
    monkeypatch.setattr(
        precision_llm_pilot,
        "_load_experiment_rows",
        lambda workbook_path, chapter_path, sample_size: (
            rows[:sample_size],
            chapter,
            tokenizer,
            workbook,
        ),
    )

    class FakeLLM:
        def complete(self, prompt: str):
            chunk_id = "chunk-0" if "chunk-0" in prompt else "chunk-1"
            return type(
                "FakeResponse",
                (),
                {
                    "text": json.dumps(
                        {
                            "chunk_id": chunk_id,
                            "chapter_id": "inflation",
                            "relevance_score": 0.9,
                            "reason": "본문이 인플레이션 개념을 설명함",
                            "subtopics": ["인플레이션의 개념"],
                            "evidence_span": (
                                "인플레이션은 물가가 지속적으로 상승하는 현상이다."
                            ),
                            "quiz_candidate": True,
                            "needs_review": False,
                            "review_status": "APPROVED",
                            "model_name": "Provider Returned Name",
                        },
                        ensure_ascii=False,
                    )
                },
            )()

    output = tmp_path / "pilot.jsonl"
    result = precision_llm_pilot.run(
        output_path=output, sample_size=1, execute=True, llm=FakeLLM()
    )
    assert result["llm_calls"] == 1
    row = json.loads(output.read_text().splitlines()[0])
    assert row["status"] == "COMPLETED"
    assert row["review_status"] == "PENDING"
    assert row["model_review_status"] == "APPROVED"
    assert row["model_name"] == "openai/gpt-5.6-sol"


def test_load_existing_pilot_reuses_matching_model_without_call(tmp_path) -> None:
    # 같은 모델의 기존 결과를 재사용하여 Notebook 재실행 시 중복 비용을 막습니다.
    output = tmp_path / "pilot.jsonl"
    output.write_text(
        json.dumps(
            {
                "model_name": "openai/gpt-5.6-sol",
                "chapter_id": "inflation",
                "keyword_candidate": True,
                "llm_call_count": 1,
                "status": "COMPLETED",
                "input_tokens_estimated": 12,
                "output_tokens_estimated": 8,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    result = precision_llm_pilot.load_existing_pilot(
        output, "openai/gpt-5.6-sol"
    )
    assert result is not None
    assert result["status"] == "REUSED_EXISTING_LLM_PILOT"
    assert result["llm_calls"] == 1
    assert precision_llm_pilot.load_existing_pilot(output, "openai/gpt-4o-mini") is None


def test_external_pilot_is_capped_at_twenty_documents(tmp_path) -> None:
    with pytest.raises(ValueError, match="capped at 20"):
        precision_llm_pilot.run(
            output_path=tmp_path / "pilot.jsonl",
            sample_size=21,
            execute=True,
        )
