# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
"""Run actual local EDA without modifying source datasets or calling an LLM."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path
from typing import Any

from app.dataset_pipeline.chunks import make_chunks, paragraphs
from app.dataset_pipeline.io import load_corpus
from app.dataset_pipeline.keywords import Chapter
from app.dataset_pipeline.tokenizer import ExactTokenizer, summarize
from scripts._pipeline_support import load_yaml, write_json

ROOT = Path(__file__).resolve().parents[1]


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _plot(
    output_dir: Path,
    source_counts: Counter[str],
    doc_tokens: list[int],
    chunk_tokens: list[int],
    keyword_counts: Counter[str],
    quality_rows: list[dict[str, Any]],
    chunk_counts: dict[str, int],
) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return "UNAVAILABLE_MATPLOTLIB"

    plt.rcParams["font.family"] = ["Apple SD Gothic Neo", "DejaVu Sans"]
    output_dir.mkdir(parents=True, exist_ok=True)

    def save_bar(path: Path, labels: list[str], values: list[int], title: str) -> None:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.bar(labels, values)
        axis.set_title(title)
        axis.tick_params(axis="x", rotation=25)
        fig.tight_layout()
        fig.savefig(path, dpi=150)
        plt.close(fig)

    save_bar(
        output_dir / "01_source_counts.png",
        list(source_counts),
        list(source_counts.values()),
        "기관별 고유 문서 수",
    )
    for filename, values, title in (
        ("02_document_text_length.png", doc_tokens, "문서 토큰 길이 분포"),
        ("03_chunk_token_length.png", chunk_tokens, "청크 토큰 길이 분포"),
    ):
        fig, axis = plt.subplots(figsize=(9, 5))
        axis.hist(values, bins=30)
        axis.set_title(title)
        axis.set_xlabel("토큰 수")
        axis.set_ylabel("문서/청크 수")
        fig.tight_layout()
        fig.savefig(output_dir / filename, dpi=150)
        plt.close(fig)
    save_bar(
        output_dir / "04_keyword_frequency.png",
        list(keyword_counts)[:20],
        list(keyword_counts.values())[:20],
        "주요 키워드 매칭 빈도",
    )
    issue_rows = [row for row in quality_rows if row["count"]]
    save_bar(
        output_dir / "05_quality_issues.png",
        [row["issue_type"] for row in issue_rows],
        [row["count"] for row in issue_rows],
        "결측·품질 문제 현황",
    )
    save_bar(
        output_dir / "06_chunk_counts.png",
        ["문서", "청크"],
        [chunk_counts["document_count"], chunk_counts["chunk_count"]],
        "청크 생성 전후 개수 비교",
    )
    return "GENERATED"


def run(
    data_dir: Path, config_path: Path, chapter_path: Path, output_dir: Path
) -> dict[str, Any]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    config = load_yaml(config_path)
    chapter_config = load_yaml(chapter_path)
    chapters = [Chapter.from_dict(item) for item in chapter_config.get("chapters", [])]
    documents, inventory = load_corpus(data_dir)
    tokenizer = ExactTokenizer(
        config.get("tokenizer", {}).get("model_alias", "gpt-4o-mini")
    )
    doc_token_counts = [tokenizer.count(document.content) for document in documents]
    text_lengths = [len(document.content) for document in documents]
    chunks = make_chunks(
        documents,
        tokenizer,
        inventory["dataset_version"],
        max_tokens=int(config.get("chunking", {}).get("max_tokens", 700)),
        overlap_tokens=int(config.get("chunking", {}).get("overlap_tokens", 100)),
    )
    chunk_token_counts = [chunk.token_count for chunk in chunks]

    source_counts = Counter(document.source for document in documents)
    source_stats = {}
    for source in sorted(source_counts):
        source_docs = [doc for doc in documents if doc.source == source]
        source_stats[source] = {
            "document_count": len(source_docs),
            "text_length_chars": summarize(len(doc.content) for doc in source_docs),
            "token_count": summarize(
                tokenizer.count(doc.content) for doc in source_docs
            ),
            "paragraph_count": summarize(
                len(paragraphs(doc.content)) for doc in source_docs
            ),
            "chunk_count": sum(chunk.source == source for chunk in chunks),
        }

    required_fields = (
        "document_id",
        "title",
        "content",
        "source_url",
        "source_locator",
        "text_hash",
    )
    quality_rows: list[dict[str, Any]] = []
    for field in required_fields:
        count = sum(not getattr(document, field) for document in documents)
        quality_rows.append(
            {
                "issue_type": f"missing_{field}",
                "count": count,
                "status": "REVIEW" if count else "PASS",
            }
        )
    quality_rows.extend(
        [
            {
                "issue_type": "unknown_source_review_status",
                "count": sum(
                    document.source_review_status == "UNKNOWN" for document in documents
                ),
                "status": "REVIEW",
            },
            {
                "issue_type": "unconfirmed_license_status",
                "count": sum(
                    document.license_status == "UNCONFIRMED" for document in documents
                ),
                "status": "REVIEW",
            },
            {
                "issue_type": "empty_content",
                "count": sum(not document.content for document in documents),
                "status": "PASS",
            },
            {
                "issue_type": "replacement_character",
                "count": sum("�" in document.content for document in documents),
                "status": "REVIEW",
            },
            {
                "issue_type": "very_short_under_20_tokens",
                "count": sum(count < 20 for count in doc_token_counts),
                "status": "REVIEW",
            },
            {
                "issue_type": "longer_than_chunk_limit",
                "count": sum(
                    count > int(config.get("chunking", {}).get("max_tokens", 700))
                    for count in doc_token_counts
                ),
                "status": "REVIEW",
            },
        ]
    )
    id_counts = Counter((doc.source, doc.document_id) for doc in documents)
    hash_counts = Counter((doc.source, doc.text_hash) for doc in documents)
    quality_rows.extend(
        [
            {
                "issue_type": "duplicate_document_id_within_source",
                "count": sum(count - 1 for count in id_counts.values() if count > 1),
                "status": "FAIL",
            },
            {
                "issue_type": "duplicate_content_hash_within_source",
                "count": sum(count - 1 for count in hash_counts.values() if count > 1),
                "status": "FAIL",
            },
        ]
    )

    keyword_counts: Counter[str] = Counter()
    for document in documents:
        text = f"{document.title} {document.content}".casefold()
        for chapter in chapters:
            for keyword in chapter.all_keywords:
                if re.sub(r"\s+", "", keyword.casefold()) in re.sub(r"\s+", "", text):
                    keyword_counts[keyword] += 1

    dataset_statistics = {
        "generated_by": "scripts/run_eda.py",
        "analysis_status": "EXECUTED_LOCAL_DATA",
        "tokenizer": {
            "kind": "tiktoken",
            "model_alias": tokenizer.model_alias,
            "encoding": tokenizer.encoding_name,
            "exact": True,
        },
        "inventory": inventory,
        "corpus": {
            "unique_document_count": len(documents),
            "document_count_by_source": dict(source_counts),
            "text_length_chars": summarize(text_lengths),
            "token_count": summarize(doc_token_counts),
            "source_stats": source_stats,
            "duplicate_counting_note": (
                "JSON and JSONL mirrors are not added together; "
                "cross-source same content is not merged."
            ),
        },
        "chunks": {
            "document_count": len(documents),
            "chunk_count": len(chunks),
            "documents_with_multiple_chunks": len(
                {chunk.document_id for chunk in chunks if chunk.chunk_index > 0}
            ),
            "token_count": summarize(chunk_token_counts),
            "settings": config.get("chunking", {}),
        },
        "keyword_frequency": dict(keyword_counts.most_common()),
        "quality": {
            "rows": quality_rows,
            "issue_count": sum(row["count"] for row in quality_rows),
        },
        "chapter_config_status": chapter_config.get("curriculum_status"),
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "dataset_statistics.json", dataset_statistics)
    write_json(output_dir / "dataset_file_inventory.json", inventory)
    _write_csv(output_dir / "dataset_quality_report.csv", quality_rows)
    _write_csv(
        output_dir / "source_statistics.csv",
        [{"source": source, **stats} for source, stats in source_stats.items()],
    )
    plot_status = _plot(
        output_dir / "figures",
        source_counts,
        doc_token_counts,
        chunk_token_counts,
        keyword_counts,
        quality_rows,
        {"document_count": len(documents), "chunk_count": len(chunks)},
    )
    dataset_statistics["visualizations"] = {
        "status": plot_status,
        "directory": str(output_dir / "figures"),
    }
    write_json(output_dir / "dataset_statistics.json", dataset_statistics)

    report = [
        "# Leren 데이터셋 EDA 보고서",
        "",
        "## 실행 상태",
        "",
        "- 실행 스크립트: `scripts/run_eda.py`",
        f"- 데이터셋 버전: `{inventory['dataset_version']}`",
        f"- 토크나이저: `{tokenizer.encoding_name}` (`tiktoken`, 실측)",
        f"- 원본 파일: {inventory['file_count']}개, "
        f"canonical 고유 문서: {len(documents)}건",
        "- JSON/JSONL 쌍은 중복 집계하지 않았고, 원본 파일 자체는 수정하지 않았습니다.",
        "",
        "## 실제 규모",
        "",
        f"- 기관별 문서: {dict(source_counts)}",
        f"- 전체 토큰: {summarize(doc_token_counts)['total']:,} tokens",
        f"- 평균 토큰: {summarize(doc_token_counts)['average']:.2f} tokens",
        f"- 중앙값 / p95: {summarize(doc_token_counts)['median']:.2f} / "
        f"{summarize(doc_token_counts)['p95']:.2f}",
        f"- 청크: {len(documents):,}건 → {len(chunks):,}건",
        "",
        "## 품질 및 해석 주의사항",
        "",
        "- BOK 데이터의 source URL·review status·license approval이 canonical "
        "파일에 없거나 미확정이므로 운영 승인으로 해석하지 않았습니다.",
        "- 챕터 설정은 production curriculum이 없어 "
        "`DRAFT_NOT_CANONICAL` 임시 파일입니다.",
        "- 키워드 매칭은 후보 추출 결과이며 관련성 확정, 확률, 정답 라벨이 아닙니다.",
        "- 상세 결과: `dataset_statistics.json`, "
        "`dataset_quality_report.csv`, `figures/`.",
        "",
        "## 기존 리포트와의 관계",
        "",
        "이번 실행은 현재 `data/` 하위 파일을 직접 읽었습니다. 이전 시점의 "
        "보고서에는 다른 BOK 스키마가 기록되어 있을 수 있으므로, 이 파일의 "
        "dataset_version과 file inventory를 기준으로 사용합니다.",
    ]
    (output_dir / "eda_report.md").write_text(
        "\n".join(report) + "\n", encoding="utf-8"
    )
    return dataset_statistics


def main() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--config", type=Path, default=ROOT / "configs/eda_config.yaml")
    parser.add_argument("--chapters", type=Path, default=ROOT / "configs/chapters.yaml")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "reports/pipeline")
    args = parser.parse_args()
    result = run(args.data_dir, args.config, args.chapters, args.output_dir)
    print(
        "documents="
        f"{result['corpus']['unique_document_count']} "
        f"chunks={result['chunks']['chunk_count']}"
    )
    print(f"average_tokens={result['corpus']['token_count']['average']:.2f}")


if __name__ == "__main__":
    main()
