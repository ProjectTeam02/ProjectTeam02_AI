# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
"""Normalize local sources and create lineage-preserving chunks."""

from __future__ import annotations

import argparse
import csv
from collections import Counter
from pathlib import Path

from app.dataset_pipeline.chunks import make_chunks
from app.dataset_pipeline.io import load_corpus
from app.dataset_pipeline.tokenizer import ExactTokenizer, summarize
from scripts._pipeline_support import load_yaml, write_json, write_jsonl

ROOT = Path(__file__).resolve().parents[1]


def run(data_dir: Path, config_path: Path, output_dir: Path) -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    config = load_yaml(config_path)
    documents, inventory = load_corpus(data_dir)
    tokenizer = ExactTokenizer(
        config.get("tokenizer", {}).get("model_alias", "gpt-4o-mini")
    )
    settings = config.get("chunking", {})
    chunks = make_chunks(
        documents,
        tokenizer,
        inventory["dataset_version"],
        max_tokens=int(settings.get("max_tokens", 700)),
        overlap_tokens=int(settings.get("overlap_tokens", 100)),
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(
        output_dir / "normalized_documents.jsonl", [doc.as_dict() for doc in documents]
    )
    write_jsonl(output_dir / "chunks.jsonl", [chunk.as_dict() for chunk in chunks])
    by_source = Counter(chunk.source for chunk in chunks)
    summary = {
        "status": "EXECUTED_LOCAL_DATA",
        "dataset_version": inventory["dataset_version"],
        "document_count": len(documents),
        "chunk_count": len(chunks),
        "chunk_count_by_source": dict(by_source),
        "chunk_token_statistics": summarize(chunk.token_count for chunk in chunks),
        "documents_with_multiple_chunks": len(
            {chunk.document_id for chunk in chunks if chunk.chunk_index > 0}
        ),
        "settings": settings,
        "source_lineage_fields": [
            "document_id",
            "source",
            "source_url",
            "source_locator",
            "text_hash",
            "dataset_version",
        ],
        "source_data_modified": False,
    }
    write_json(output_dir / "chunk_summary.json", summary)
    with (output_dir / "chunk_counts.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["source", "document_count", "chunk_count"]
        )
        writer.writeheader()
        for source in sorted({doc.source for doc in documents}):
            writer.writerow(
                {
                    "source": source,
                    "document_count": sum(doc.source == source for doc in documents),
                    "chunk_count": by_source[source],
                }
            )
    return summary


def main() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/eda_config.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/processed")
    args = parser.parse_args()
    summary = run(args.data_dir, args.config, args.output_dir)
    print(
        "normalized_documents="
        f"{summary['document_count']} chunks={summary['chunk_count']}"
    )


if __name__ == "__main__":
    main()
