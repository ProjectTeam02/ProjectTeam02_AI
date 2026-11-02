# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
"""Extract broad keyword candidates and a non-match review sample."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

from app.dataset_pipeline.chunks import make_chunks
from app.dataset_pipeline.io import load_corpus
from app.dataset_pipeline.keywords import Chapter, keyword_candidates, sample_unmatched
from app.dataset_pipeline.tokenizer import ExactTokenizer
from scripts._pipeline_support import load_yaml, write_json, write_jsonl

# 스크립트 실행 위치와 무관하게 프로젝트 기준 경로를 사용합니다.
ROOT = Path(__file__).resolve().parents[1]


def _write_csv(path: Path, rows: list[dict]) -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    # 후보가 0건이어도 헤더를 남겨 후속 검수 단계가 동일하게 동작하게 합니다.
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["status"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def run(
    data_dir: Path,
    config_path: Path,
    chapter_path: Path,
    output_dir: Path,
    chunks_path: Path | None = None,
) -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    # 처리 청크가 있으면 재사용하고, 없을 때만 원본에서 정규화·청크 생성을 수행합니다.
    config = load_yaml(config_path)
    chapter_config = load_yaml(chapter_path)
    chapters = [Chapter.from_dict(item) for item in chapter_config.get("chapters", [])]
    tokenizer = ExactTokenizer(
        config.get("tokenizer", {}).get("model_alias", "gpt-4o-mini")
    )
    if chunks_path and chunks_path.is_file():
        # 원본이 없어도 이미 생성된 청크 아티팩트로 후보 추출을 재현할 수 있습니다.
        import json

        chunk_rows = [
            json.loads(line)
            for line in chunks_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        from app.dataset_pipeline.chunks import Chunk

        chunks = [Chunk(**row) for row in chunk_rows]
        dataset_version = chunks[0].dataset_version if chunks else "unknown"
        input_mode = "processed_chunks_artifact"
    else:
        # 이 경로에서는 load_corpus가 원본 파일 부재를 예외로 알려줍니다.
        documents, inventory = load_corpus(data_dir)
        dataset_version = inventory["dataset_version"]
        input_mode = "canonical_source_exports"
        chunks = make_chunks(
            documents,
            tokenizer,
            dataset_version,
            max_tokens=int(config.get("chunking", {}).get("max_tokens", 700)),
            overlap_tokens=int(config.get("chunking", {}).get("overlap_tokens", 100)),
        )

    # 키워드는 최종 라벨이 아니라 넓은 후보군을 만드는 1차 필터입니다.
    candidates, summary = keyword_candidates(chunks, chapters)
    sample = sample_unmatched(
        chunks,
        candidates,
        sample_size=int(config.get("sampling", {}).get("unmatched_chunks", 100)),
    )
    # 실행 방식·LLM 호출 여부를 함께 저장해 결과의 재현 조건을 남깁니다.
    summary.update(
        {
            "status": "EXECUTED_KEYWORD_CANDIDATE_EXTRACTION",
            "dataset_version": dataset_version,
            "chapter_config_version": chapter_config.get("config_version"),
            "curriculum_status": chapter_config.get("curriculum_status"),
            "unmatched_sample_count": len(sample),
            "llm_calls": 0,
            "permanent_deletion": False,
            "input_mode": input_mode,
        }
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    # JSONL은 후속 파이프라인용, CSV는 사람이 검토하기 위한 형식입니다.
    write_jsonl(output_dir / "keyword_candidates.jsonl", candidates)
    write_jsonl(output_dir / "unmatched_sample.jsonl", sample)
    write_json(output_dir / "keyword_summary.json", summary)
    _write_csv(output_dir / "keyword_candidates.csv", candidates)
    _write_csv(output_dir / "unmatched_sample.csv", sample)
    # 보고서 디렉터리에도 동일한 후보 파일을 남겨 검토자가 쉽게 확인합니다.
    _write_csv(ROOT / "reports" / "keyword_candidates.csv", candidates)
    return summary


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
        "--output-dir", type=Path, default=ROOT / "data/labeled/keyword"
    )
    args = parser.parse_args()
    summary = run(
        args.data_dir, args.config, args.chapters, args.output_dir, args.chunks
    )
    print(
        f"chunks={summary['total_chunks']} candidate_rows={summary['candidate_rows']}"
    )
    print(f"candidate_rate={summary['candidate_chunk_rate']:.4f}")


if __name__ == "__main__":
    main()
