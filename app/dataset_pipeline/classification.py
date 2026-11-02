# 파일 역할: 경제·금융 데이터의 정규화, 청크, 키워드, 분류 전처리를 담당합니다.
"""LLM classification contract, prompt construction, and offline validation."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

CLASSIFICATION_OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "chunk_id",
        "chapter_id",
        "relevance_score",
        "reason",
        "subtopics",
        "evidence_span",
        "quiz_candidate",
        "needs_review",
    ],
    "properties": {
        "chunk_id": {"type": "string"},
        "chapter_id": {"type": "string"},
        "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
        "reason": {"type": "string"},
        "subtopics": {"type": "array", "items": {"type": "string"}},
        "evidence_span": {"type": ["string", "null"]},
        "quiz_candidate": {"type": "boolean"},
        "needs_review": {"type": "boolean"},
        "model_name": {"type": "string"},
        "classified_at": {"type": "string"},
        "prompt_version": {"type": "string"},
        "rubric_version": {"type": "string"},
        "review_status": {
            "type": "string",
            "enum": ["PENDING", "APPROVED", "REJECTED", "NEEDS_REVISION"],
        },
    },
}


def build_classification_prompt(
    chunk: dict[str, Any], chapter: dict[str, Any], prompt_version: str = "llm-v1"
) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    payload = {
        "chunk_id": chunk.get("chunk_id"),
        "title": chunk.get("title"),
        "content": chunk.get("content"),
        "chapter": {
            "chapter_id": chapter.get("chapter_id"),
            "chapter_name": chapter.get("chapter_name"),
            "definition": chapter.get("chapter_definition", ""),
            "include_criteria": chapter.get("include_criteria", ""),
            "exclude_criteria": chapter.get("exclude_criteria", ""),
            "rubric_version": chapter.get("rubric_version", "draft-v1"),
        },
    }
    return (
        "You are a Korean economics education dataset reviewer. Classify the "
        "chunk for the supplied chapter. A relevance score is a rubric score, "
        "not a probability or measured accuracy. Use only evidence in the chunk. "
        "If evidence is insufficient, set needs_review=true. Return JSON only "
        f"conforming to the supplied schema. Prompt version: {prompt_version}.\n"
        + json.dumps(payload, ensure_ascii=False, indent=2)
    )


def validate_classification_output(
    value: dict[str, Any], expected_chunk_id: str, expected_chapter_id: str
) -> dict[str, Any]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    required = {
        "chunk_id",
        "chapter_id",
        "relevance_score",
        "reason",
        "subtopics",
        "evidence_span",
        "quiz_candidate",
        "needs_review",
    }
    missing = sorted(required - value.keys())
    if missing:
        raise ValueError(f"classification output missing fields: {missing}")
    if (
        value["chunk_id"] != expected_chunk_id
        or value["chapter_id"] != expected_chapter_id
    ):
        raise ValueError("classification output lineage does not match input")
    score = value["relevance_score"]
    if (
        isinstance(score, bool)
        or not isinstance(score, (int, float))
        or not 0 <= score <= 1
    ):
        raise ValueError("relevance_score must be a number between 0 and 1")
    if not isinstance(value["reason"], str) or not value["reason"].strip():
        raise ValueError("reason must be a non-empty string")
    if not isinstance(value["subtopics"], list) or not all(
        isinstance(item, str) for item in value["subtopics"]
    ):
        raise ValueError("subtopics must be a string array")
    if not isinstance(value["quiz_candidate"], bool) or not isinstance(
        value["needs_review"], bool
    ):
        raise ValueError("quiz_candidate and needs_review must be booleans")
    result = dict(value)
    result.setdefault("review_status", "PENDING")
    result.setdefault("classified_at", datetime.now(timezone.utc).isoformat())
    return result


def make_dry_run_record(
    chunk: dict[str, Any],
    chapter: dict[str, Any],
    input_tokens: int,
    output_tokens: int,
) -> dict[str, Any]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return {
        "chunk_id": chunk["chunk_id"],
        "chapter_id": chapter["chapter_id"],
        "status": "DRY_RUN_NOT_CALLED",
        "input_tokens": input_tokens,
        "expected_output_tokens": output_tokens,
        "llm_call_count": 0,
        "review_status": "PENDING",
    }
