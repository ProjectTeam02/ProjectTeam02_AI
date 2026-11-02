# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
"""Estimate LLM classification tokens/cost without making API calls."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from app.dataset_pipeline.chunks import Chunk, make_chunks
from app.dataset_pipeline.classification import build_classification_prompt
from app.dataset_pipeline.io import load_corpus
from app.dataset_pipeline.keywords import Chapter
from app.dataset_pipeline.tokenizer import ExactTokenizer, summarize
from scripts._pipeline_support import load_yaml, write_json

ROOT = Path(__file__).resolve().parents[1]


def _load_chunks(path: Path) -> list[Chunk]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return [
        Chunk(**json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def run(
    data_dir: Path,
    config_path: Path,
    chapter_path: Path,
    chunks_path: Path,
    candidates_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    config = load_yaml(config_path)
    chapter_config = load_yaml(chapter_path)
    chapters = [Chapter.from_dict(item) for item in chapter_config.get("chapters", [])]
    chapter_by_id = {chapter.chapter_id: chapter for chapter in chapters}
    tokenizer = ExactTokenizer(
        config.get("tokenizer", {}).get("model_alias", "gpt-4o-mini")
    )
    if chunks_path.is_file():
        chunks = _load_chunks(chunks_path)
    else:
        documents, inventory = load_corpus(data_dir)
        chunks = make_chunks(
            documents,
            tokenizer,
            inventory["dataset_version"],
            max_tokens=int(config.get("chunking", {}).get("max_tokens", 700)),
            overlap_tokens=int(config.get("chunking", {}).get("overlap_tokens", 100)),
        )
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    candidate_rows = []
    if candidates_path.is_file():
        candidate_rows = [
            json.loads(line)
            for line in candidates_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    else:
        raise FileNotFoundError(
            f"{candidates_path} is required; run scripts/keyword_filter.py first"
        )

    prompt_version = str(
        config.get("classification", {}).get("prompt_version", "llm-v1")
    )
    expected_output = int(
        config.get("classification", {}).get("expected_output_tokens", 180)
    )
    input_counts: list[int] = []
    valid_pairs = 0
    skipped = 0
    for row in candidate_rows:
        chunk = chunk_by_id.get(row.get("chunk_id"))
        chapter = chapter_by_id.get(row.get("chapter_id"))
        if chunk is None or chapter is None:
            skipped += 1
            continue
        prompt = build_classification_prompt(
            chunk.as_dict(),
            chapter.__dict__
            if hasattr(chapter, "__dict__")
            else {
                "chapter_id": chapter.chapter_id,
                "chapter_name": chapter.chapter_name,
                "chapter_definition": chapter.chapter_definition,
                "include_criteria": chapter.include_criteria,
                "exclude_criteria": chapter.exclude_criteria,
                "rubric_version": chapter.rubric_version,
            },
            prompt_version=prompt_version,
        )
        input_counts.append(tokenizer.count(prompt))
        valid_pairs += 1

    classification = config.get("classification", {})
    rpm = classification.get("requests_per_minute_assumption")
    models = []
    for model in classification.get("models", []):
        input_total = sum(input_counts)
        output_total = valid_pairs * expected_output
        input_price = model.get("input_usd_per_1m_tokens")
        output_price = model.get("output_usd_per_1m_tokens")
        cost = None
        cost_status = "NOT_CALCULATED_PRICE_UNCONFIRMED"
        if input_price is not None and output_price is not None:
            cost = input_total / 1_000_000 * float(
                input_price
            ) + output_total / 1_000_000 * float(output_price)
            cost_status = "CALCULATED_FROM_CONFIG_PRICES"
        duration = valid_pairs / float(rpm) if rpm else None
        models.append(
            {
                "model": model.get("model"),
                "input_tokens": input_total,
                "expected_output_tokens": output_total,
                "total_tokens": input_total + output_total,
                "input_usd_per_1m_tokens": input_price,
                "output_usd_per_1m_tokens": output_price,
                "estimated_cost_usd": cost,
                "cost_status": cost_status,
                "requests_per_minute_assumption": rpm,
                "estimated_minutes": duration,
            }
        )
    result = {
        "status": "DRY_RUN_ONLY_NO_LLM_CALL",
        "dataset_version": chunks[0].dataset_version if chunks else None,
        "candidate_pair_count": len(candidate_rows),
        "valid_candidate_pair_count": valid_pairs,
        "skipped_missing_lineage_count": skipped,
        "input_token_statistics": summarize(input_counts),
        "expected_output_tokens_per_call": expected_output,
        "prompt_version": prompt_version,
        "rubric_versions": sorted({chapter.rubric_version for chapter in chapters}),
        "models": models,
        "price_policy": (
            "Prices remain null unless explicitly confirmed and supplied in "
            "configs/eda_config.yaml."
        ),
        "llm_calls": 0,
        "api_keys_read": False,
    }
    write_json(output_path, result)
    return result


def main() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/eda_config.yaml")
    parser.add_argument("--chapters", type=Path, default=ROOT / "configs/chapters.yaml")
    parser.add_argument(
        "--chunks", type=Path, default=ROOT / "data/processed/chunks.jsonl"
    )
    parser.add_argument(
        "--candidates",
        type=Path,
        default=ROOT / "data/labeled/keyword/keyword_candidates.jsonl",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "reports/pipeline/classification_cost_estimate.json",
    )
    args = parser.parse_args()
    result = run(
        args.data_dir,
        args.config,
        args.chapters,
        args.chunks,
        args.candidates,
        args.output,
    )
    print(
        "candidate_pairs="
        f"{result['valid_candidate_pair_count']} "
        f"llm_calls={result['llm_calls']}"
    )
    for model in result["models"]:
        print(
            f"{model['model']}: tokens={model['total_tokens']} "
            f"cost={model['estimated_cost_usd']}"
        )


if __name__ == "__main__":
    main()
