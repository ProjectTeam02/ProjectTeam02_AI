"""Run a small, explicitly enabled LLM classification pilot.

The main precision EDA remains offline.  This module is a separate opt-in
experiment so an API key cannot accidentally trigger a large paid run from a
notebook's first cell.  Pilot outputs are written to the ignored
``data/labeled/precision`` directory and remain pending for human review.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.dataset_pipeline.classification import (  # noqa: E402
    build_classification_prompt,
    validate_classification_output,
)
from app.dataset_pipeline.keywords import (  # noqa: E402
    Chapter,
    classify_chunk_by_keywords,
)
from app.dataset_pipeline.labels import (  # noqa: E402
    analyze_label_rows,
    discover_label_workbook,
    read_xlsx_rows,
)
from app.dataset_pipeline.tokenizer import ExactTokenizer, summarize  # noqa: E402
from app.rag.indexing.llm_factory import LLMFactory  # noqa: E402
from scripts._pipeline_support import load_yaml  # noqa: E402
from scripts.rebuild_precision_pipeline import (  # noqa: E402
    _make_chunk,
    _records,
)

DEFAULT_OUTPUT = ROOT / "data/labeled/precision/llm_pilot_results.jsonl"
DEFAULT_CHAPTERS = ROOT / "configs/chapters.yaml"
DEFAULT_SAMPLE_SIZE = 10


def _json_object(text: str) -> dict[str, Any]:
    """Extract one JSON object from a plain or Markdown-wrapped response."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM response does not contain a JSON object")
    value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("LLM response JSON must be an object")
    return value


def _response_text(response: Any) -> str:
    """Read text from LlamaIndex responses without depending on one version."""
    text = getattr(response, "text", None)
    if isinstance(text, str):
        return text
    return str(response)


def _response_usage(response: Any) -> dict[str, int | None]:
    """Read provider usage when available; local estimates remain separate."""
    raw = getattr(response, "raw", None)
    usage = raw.get("usage") if isinstance(raw, dict) else None
    if not isinstance(usage, dict):
        return {"input_tokens": None, "output_tokens": None}
    return {
        "input_tokens": usage.get("prompt_tokens") or usage.get("input_tokens"),
        "output_tokens": usage.get("completion_tokens")
        or usage.get("output_tokens"),
    }


def _response_model(response: Any) -> str | None:
    """Read provider metadata, not a model name typed by the LLM."""
    raw = getattr(response, "raw", None)
    candidates: list[Any] = [getattr(response, "model", None)]
    if isinstance(raw, dict):
        candidates.append(raw.get("model"))
    else:
        candidates.append(getattr(raw, "model", None))
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _display_path(path: Path) -> str:
    """Prefer a repository-relative path while supporting test fixtures."""
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _load_experiment_rows(
    workbook_path: Path | None,
    chapter_path: Path,
    sample_size: int,
) -> tuple[list[dict[str, Any]], Chapter, ExactTokenizer, Path]:
    """Load a balanced pilot sample without exposing gold labels to the prompt."""
    if sample_size <= 0:
        raise ValueError("sample_size must be greater than zero")
    workbook = workbook_path
    if workbook is None:
        candidates = discover_label_workbook(ROOT)
        if not candidates:
            raise FileNotFoundError("라벨링.xlsx 또는 라벨 파일을 찾지 못했습니다.")
        workbook = candidates[0]
    rows = read_xlsx_rows(workbook)
    analysis = analyze_label_rows(rows, workbook)
    records = _records(rows, analysis["detected_columns"])

    payload = load_yaml(chapter_path)
    chapters = payload.get("chapters", [])
    if not chapters:
        raise ValueError(f"{chapter_path}에 챕터가 없습니다.")
    chapter = Chapter.from_dict(chapters[0])
    tokenizer = ExactTokenizer("gpt-4o-mini")

    prepared: list[dict[str, Any]] = []
    for record in records:
        chunk = _make_chunk(record, tokenizer)
        keyword_result = classify_chunk_by_keywords(chunk, chapter)
        prepared.append(
            {
                "record": record,
                "chunk": chunk,
                "keyword_candidate": bool(keyword_result["candidate"]),
                "matched_keywords": keyword_result["matched_keywords"],
                "sampling_key": _stable_key(record["document_id"]),
            }
        )

    # 후보와 비후보를 함께 넣어 LLM의 오탐·누락 가능성을 확인합니다.
    candidates = sorted(
        [item for item in prepared if item["keyword_candidate"]],
        key=lambda item: item["sampling_key"],
    )
    non_candidates = sorted(
        [item for item in prepared if not item["keyword_candidate"]],
        key=lambda item: item["sampling_key"],
    )
    candidate_count = min(len(candidates), max(1, sample_size // 2))
    selected = candidates[:candidate_count]
    remaining = sample_size - len(selected)
    selected.extend(non_candidates[:remaining])
    if len(selected) < sample_size:
        selected.extend(candidates[len(selected) : sample_size])
    selected = selected[:sample_size]

    result: list[dict[str, Any]] = []
    for item in selected:
        result.append(
            {
                "record": item["record"],
                "chunk": item["chunk"],
                "keyword_candidate": item["keyword_candidate"],
                "matched_keywords": item["matched_keywords"],
                "sampling_method": (
                    "stable_keyword_candidate_and_non_candidate_sample"
                ),
            }
        )
    return result, chapter, tokenizer, workbook


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def load_existing_pilot(
    output_path: Path, expected_model: str, expected_chapter_id: str = "inflation"
) -> dict[str, Any] | None:
    """Reuse a matching local pilot result without making another API call."""
    if not output_path.is_file():
        return None
    rows = [
        json.loads(line)
        for line in output_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if not rows:
        return None
    if any(row.get("model_name") != expected_model for row in rows):
        return None
    if any(row.get("chapter_id") != expected_chapter_id for row in rows):
        return None
    return {
        "status": "REUSED_EXISTING_LLM_PILOT",
        "chapter_id": expected_chapter_id,
        "sample_size": len(rows),
        "candidate_sample_count": sum(
            bool(row.get("keyword_candidate")) for row in rows
        ),
        "non_candidate_sample_count": sum(
            not bool(row.get("keyword_candidate")) for row in rows
        ),
        "llm_calls": sum(int(row.get("llm_call_count", 0)) for row in rows),
        "failed_calls": sum(row.get("status") == "FAILED" for row in rows),
        "input_token_estimate": summarize(
            [int(row["input_tokens_estimated"]) for row in rows]
        ),
        "output_token_estimate": summarize(
            [int(row["output_tokens_estimated"]) for row in rows]
        ),
        "provider_response_models": sorted(
            {
                row["provider_response_model"]
                for row in rows
                if row.get("provider_response_model")
            }
        ),
        "output_path": _display_path(output_path),
        "api_keys_read": False,
        "gold_labels_sent_to_model": False,
        "metrics_status": "NOT_EVALUATED_NEEDS_INDEPENDENT_GOLD",
    }


def run(
    workbook_path: Path | None = None,
    chapter_path: Path = DEFAULT_CHAPTERS,
    output_path: Path = DEFAULT_OUTPUT,
    sample_size: int = DEFAULT_SAMPLE_SIZE,
    execute: bool = False,
    llm: Any | None = None,
) -> dict[str, Any]:
    """Prepare a dry-run or execute an explicitly enabled small LLM pilot."""
    rows, chapter, tokenizer, workbook = _load_experiment_rows(
        workbook_path, chapter_path, sample_size
    )
    settings = get_settings()
    prompt_version = "llm-v1"
    results: list[dict[str, Any]] = []
    input_counts: list[int] = []
    output_counts: list[int] = []
    call_count = 0

    for item in rows:
        chunk = item["chunk"]
        prompt = build_classification_prompt(
            chunk.as_dict(),
            {
                "chapter_id": chapter.chapter_id,
                "chapter_name": chapter.chapter_name,
                "chapter_definition": chapter.chapter_definition,
                "include_criteria": chapter.include_criteria,
                "exclude_criteria": chapter.exclude_criteria,
                "rubric_version": chapter.rubric_version,
            },
            prompt_version=prompt_version,
        )
        estimated_input = tokenizer.count(prompt)
        input_counts.append(estimated_input)
        base = {
            "chunk_id": chunk.chunk_id,
            "document_id": chunk.document_id,
            "chapter_id": chapter.chapter_id,
            "keyword_candidate": item["keyword_candidate"],
            "matched_keywords": item["matched_keywords"],
            "sampling_method": item["sampling_method"],
            "model_name": settings.llm_model,
            "prompt_version": prompt_version,
            "rubric_version": chapter.rubric_version,
            "input_tokens_estimated": estimated_input,
            "review_status": "PENDING",
            "classified_at": datetime.now(timezone.utc).isoformat(),
        }
        if not execute:
            results.append(
                {
                    **base,
                    "status": "DRY_RUN_NOT_CALLED",
                    "llm_call_count": 0,
                    "output_tokens_estimated": 180,
                }
            )
            continue

        if llm is None:
            llm = LLMFactory(settings).create()
        started = time.perf_counter()
        raw_text: str | None = None
        try:
            response = llm.complete(prompt)
            raw_text = _response_text(response)
            usage = _response_usage(response)
            provider_response_model = _response_model(response)
            parsed = _json_object(raw_text)
            validated = validate_classification_output(
                parsed, chunk.chunk_id, chapter.chapter_id
            )
            # 모델의 review_status는 참고용으로만 보존합니다.
            # 최종 승인 상태는 사람이 결정합니다.
            model_review_status = validated.get("review_status")
            # 모델이 응답에 임의로 넣은 model_name은 식별 근거로 사용하지 않습니다.
            validated.pop("model_name", None)
            # provider가 반환한 이름은 요청 모델의 식별자를 대체하지 못합니다.
            validated["model_name"] = settings.llm_model
            validated["review_status"] = "PENDING"
            evidence = validated.get("evidence_span")
            evidence_valid = not evidence or str(evidence) in chunk.content
            if not evidence_valid:
                validated["needs_review"] = True
            output_estimated = tokenizer.count(raw_text)
            output_counts.append(output_estimated)
            result_status = (
                "COMPLETED"
                if evidence_valid
                else "NEEDS_REVIEW_INVALID_EVIDENCE"
            )
            results.append(
                {
                    **base,
                    **validated,
                    "status": result_status,
                    "llm_call_count": 1,
                    "latency_seconds": round(time.perf_counter() - started, 3),
                    "input_tokens_actual": usage["input_tokens"],
                    "output_tokens_actual": usage["output_tokens"],
                    "output_tokens_estimated": output_estimated,
                    "evidence_span_valid": evidence_valid,
                    "model_review_status": model_review_status,
                    "provider_response_model": provider_response_model,
                }
            )
            call_count += 1
        except Exception as exc:  # noqa: BLE001 - one bad response must not lose the batch
            results.append(
                {
                    **base,
                    "status": "FAILED",
                    "llm_call_count": 1,
                    "latency_seconds": round(time.perf_counter() - started, 3),
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "raw_response": locals().get("raw_text"),
                }
            )
            call_count += 1

    _write_jsonl(output_path, results)
    return {
        "status": "EXECUTED_LLM_PILOT" if execute else "DRY_RUN_ONLY_NO_LLM_CALL",
        "input_file": _display_path(workbook),
        "chapter_id": chapter.chapter_id,
        "sample_size": len(rows),
        "candidate_sample_count": sum(item["keyword_candidate"] for item in rows),
        "non_candidate_sample_count": sum(
            not item["keyword_candidate"] for item in rows
        ),
        "llm_calls": call_count,
        "failed_calls": sum(result["status"] == "FAILED" for result in results),
        "input_token_estimate": summarize(input_counts),
        "output_token_estimate": summarize(output_counts),
        "provider_response_models": sorted(
            {
                result["provider_response_model"]
                for result in results
                if result.get("provider_response_model")
            }
        ),
        "output_path": str(output_path.relative_to(ROOT))
        if output_path.is_relative_to(ROOT)
        else str(output_path),
        "api_keys_read": bool(execute),
        "gold_labels_sent_to_model": False,
        "metrics_status": "NOT_EVALUATED_NEEDS_INDEPENDENT_GOLD",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=None)
    parser.add_argument("--chapters", type=Path, default=DEFAULT_CHAPTERS)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Make the explicitly requested small external LLM pilot calls.",
    )
    args = parser.parse_args()
    result = run(
        workbook_path=args.workbook,
        chapter_path=args.chapters,
        output_path=args.output,
        sample_size=args.sample_size,
        execute=args.execute,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
