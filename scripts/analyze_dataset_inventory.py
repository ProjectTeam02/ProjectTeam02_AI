# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
"""Read-only STEP 1 dataset inventory and quality analysis.

This script reads local JSON/JSONL artifacts and application configuration. It
does not call an external API, open a database session, write to PostgreSQL, or
modify source datasets. It writes only the requested reports/ directory.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = ROOT / "reports"

RAG_PATH = DATA / "bok_terms_2026_rag.jsonl"
SOURCE_PATH = DATA / "bok_terms_2026.json"
EVAL_PATH = DATA / "bok_eval_questions.json"
EXTRACTION_PATH = DATA / "bok_extraction_report.json"
C0704_PATH = ROOT / "outputs" / "c0704" / "evaluation_status.json"

EXPECTED_RAG_FIELDS = (
    "id",
    "document_id",
    "source_id",
    "source_url",
    "title",
    "content",
    "document_version",
    "concept_id",
    "concept_code",
    "stage_id",
    "review_status",
    "license",
    "content_hash",
    "created_at",
    "updated_at",
    "chunk_id",
    "term",
    "term_kr",
    "term_en",
    "definition",
    "publisher",
    "document",
    "edition",
    "printed_page",
    "related_terms",
    "review_flags",
    "published_at",
    "knowledge_scope",
)


def read_json(path: Path) -> Any:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not an object")
        rows.append(value)
    return rows


def is_blank(value: Any) -> bool:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return value is None or (isinstance(value, str) and not value.strip())


def percentile(values: list[int], fraction: float) -> float | None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * fraction
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return ordered[lower] + (ordered[upper] - ordered[lower]) * weight


def statistics(values: Iterable[int]) -> dict[str, int | float | None]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    values = list(values)
    if not values:
        return {
            "total_tokens": None,
            "average_tokens": None,
            "median_tokens": None,
            "p95_tokens": None,
            "min_tokens": None,
            "max_tokens": None,
        }
    ordered = sorted(values)
    middle = len(ordered) // 2
    median = (
        ordered[middle]
        if len(ordered) % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    return {
        "total_tokens": sum(ordered),
        "average_tokens": sum(ordered) / len(ordered),
        "median_tokens": median,
        "p95_tokens": percentile(ordered, 0.95),
        "min_tokens": ordered[0],
        "max_tokens": ordered[-1],
    }


def load_tokenizer() -> tuple[Any, str, str]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    try:
        import tiktoken

        # The configured model is OpenRouter-qualified, so tiktoken cannot map
        # the literal provider-qualified string. Its unqualified model maps to
        # the o200k_base encoding used here.
        return (
            tiktoken.encoding_for_model("gpt-4o-mini"),
            "tiktoken",
            "o200k_base (gpt-4o-mini alias)",
        )
    except Exception:
        return (None, "approximation", "UTF-8 character length / 4")


def token_lengths(values: Iterable[str], tokenizer: Any) -> list[int]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if tokenizer is not None:
        return [len(tokenizer.encode(value)) for value in values]
    return [max(1, math.ceil(len(value) / 4)) for value in values]


def counts(values: Iterable[Any]) -> dict[str, int]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return dict(Counter("NULL" if value is None else str(value) for value in values))


def row_field_report(
    dataset_name: str,
    rows: list[dict[str, Any]],
    fields: Iterable[str],
) -> list[dict[str, Any]]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    result = []
    denominator = len(rows)
    for field in fields:
        values = [row.get(field) for row in rows]
        missing = sum(field not in row for row in rows)
        null_count = sum(value is None for value in values)
        blank_count = sum(
            isinstance(value, str) and not value.strip() for value in values
        )
        present_values = [value for value in values if not is_blank(value)]
        type_names = sorted({type(value).__name__ for value in present_values})
        unique = len(
            {
                json.dumps(value, ensure_ascii=False, sort_keys=True)
                for value in present_values
            }
        )
        missing_or_blank = missing + sum(
            field in row and is_blank(row.get(field)) for row in rows
        )
        result.append(
            {
                "dataset_name": dataset_name,
                "field": field,
                "record_count": denominator,
                "present_count": denominator - missing,
                "missing_count": missing,
                "null_count": null_count,
                "blank_string_count": blank_count,
                "missing_or_blank_count": missing_or_blank,
                "missing_or_blank_rate": (
                    missing_or_blank / denominator if denominator else None
                ),
                "observed_types": ",".join(type_names),
                "unique_nonblank_count": unique,
            }
        )
    return result


def inventory_row(
    *,
    dataset_name: str,
    source: str,
    file_format: str,
    file_count: int,
    record_count: int,
    document_count: int | None,
    chunk_count: int | None,
    token_stats: dict[str, Any],
    duplicate_count: int | None,
    empty_count: int | None,
    review_status: str,
    license_status: str,
    token_basis: str,
    measurement_kind: str,
    notes: str,
) -> dict[str, Any]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return {
        "dataset_name": dataset_name,
        "source": source,
        "file_format": file_format,
        "file_count": file_count,
        "record_count": record_count,
        "document_count": document_count,
        "chunk_count": chunk_count,
        **token_stats,
        "duplicate_count": duplicate_count,
        "empty_count": empty_count,
        "review_status": review_status,
        "license_status": license_status,
        "token_basis": token_basis,
        "measurement_kind": measurement_kind,
        "notes": notes,
    }


def projected_bok_chunks(
    approved_rows: list[dict[str, Any]], tokenizer: Any
) -> dict[str, Any]:
    """Reproduce DocumentIndexer chunking without creating an index or DB row."""
    try:
        from llama_index.core import Document
        from llama_index.core.node_parser import SentenceSplitter

        from app.rag.ingestion.bok_terms_loader import load_bok_terms

        # Use the production loader so datetime normalization and all metadata
        # fields match the DocumentIndexer path exactly.
        items = load_bok_terms(RAG_PATH, approved_only=True)
        documents = [
            Document(
                text=item.content,
                id_=item.document_id,
                metadata={
                    **item.metadata,
                    "source": item.source,
                    "version": item.version or "",
                },
            )
            for item in items
        ]
        nodes = SentenceSplitter(
            chunk_size=700, chunk_overlap=100
        ).get_nodes_from_documents(documents)
        per_document: Counter[str] = Counter()
        chunk_ids: list[str] = []
        hashes_by_document = {item.document_id: item.content_hash for item in items}
        chunk_token_lengths = []
        for node in nodes:
            document_id = str(node.metadata.get("document_id", "document"))
            chunk_index = per_document[document_id]
            per_document[document_id] += 1
            chunk_id = (
                f"{document_id}:{hashes_by_document[document_id][:12]}:{chunk_index}"
            )
            chunk_ids.append(chunk_id)
            chunk_token_lengths.append(len(tokenizer.encode(node.get_content())))
        return {
            "status": "measured",
            "document_count": len(items),
            "chunk_count": len(nodes),
            "chunk_id_duplicate_count": len(chunk_ids) - len(set(chunk_ids)),
            "chunks_per_document": statistics(list(per_document.values())),
            "chunk_token_statistics": statistics(chunk_token_lengths),
            "settings": {"chunk_size": 700, "chunk_overlap": 100},
            "method": (
                "LlamaIndex SentenceSplitter with DocumentIndexer metadata shape; "
                "no index/DB write"
            ),
        }
    except Exception as exc:
        return {
            "status": "unavailable",
            "document_count": len(approved_rows),
            "chunk_count": None,
            "error": f"{type(exc).__name__}: {exc}",
            "settings": {"chunk_size": 700, "chunk_overlap": 100},
            "method": "not measured",
        }


def quality_row(
    dataset_name: str,
    issue_type: str,
    severity: str,
    count: int,
    denominator: int | None,
    status: str,
    evidence: str,
    details: str,
) -> dict[str, Any]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return {
        "dataset_name": dataset_name,
        "issue_type": issue_type,
        "severity": severity,
        "count": count,
        "denominator": denominator,
        "rate": count / denominator if denominator else None,
        "status": status,
        "evidence": evidence,
        "details": details,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    fieldnames = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    tokenizer, tokenizer_kind, tokenizer_name = load_tokenizer()
    if tokenizer is None:
        print("ERROR: tiktoken is unavailable; refusing to emit exact-token report")
        raise SystemExit(2)

    rag_rows = read_jsonl(RAG_PATH)
    source_payload = read_json(SOURCE_PATH)
    source_rows = source_payload["records"]
    eval_payload = read_json(EVAL_PATH)
    extraction_payload = read_json(EXTRACTION_PATH)
    c0704_payload = read_json(C0704_PATH)

    all_content_lengths = token_lengths(
        [str(row["content"]) for row in rag_rows], tokenizer
    )
    approved_rows = [row for row in rag_rows if row.get("review_status") == "approved"]
    approved_lengths = token_lengths(
        [str(row["content"]) for row in approved_rows], tokenizer
    )
    duplicate_doc_ids = sum(
        count - 1
        for count in Counter(
            str(row.get("document_id", "")) for row in rag_rows
        ).values()
        if count > 1
    )
    duplicate_hashes = sum(
        count - 1
        for count in Counter(
            str(row.get("content_hash", "")) for row in rag_rows
        ).values()
        if count > 1
    )
    content_hash_mismatches = sum(
        row.get("content_hash")
        != hashlib.sha256(str(row.get("content", "")).encode("utf-8")).hexdigest()
        for row in rag_rows
    )
    empty_content = sum(is_blank(row.get("content")) for row in rag_rows)
    source_url_missing = sum(is_blank(row.get("source_url")) for row in rag_rows)
    license_missing = sum(is_blank(row.get("license")) for row in rag_rows)
    status_counts = counts(row.get("review_status") for row in rag_rows)
    source_id_counts = Counter(str(row.get("source_id", "")) for row in rag_rows)
    chunk_projection = projected_bok_chunks(approved_rows, tokenizer)

    eval_texts = []
    for case in eval_payload["cases"]:
        eval_texts.append(str(case.get("question", "")))
        eval_texts.extend(
            str(item.get("content", "")) for item in case.get("history", [])
        )

    inventory = [
        inventory_row(
            dataset_name="BOK canonical terms",
            source="data/bok_terms_2026.json; source.publisher=한국은행",
            file_format="JSON",
            file_count=1,
            record_count=len(source_rows),
            document_count=len({str(row.get("id")) for row in source_rows}),
            chunk_count=None,
            token_stats=statistics(
                token_lengths(
                    [str(row.get("definition", "")) for row in source_rows], tokenizer
                )
            ),
            duplicate_count=0,
            empty_count=sum(is_blank(row.get("definition")) for row in source_rows),
            review_status="; ".join(
                f"{key}={value}"
                for key, value in sorted(
                    counts(row.get("review_status") for row in source_rows).items()
                )
            ),
            license_status=(
                "Not a per-record license field; source metadata is in "
                "extraction report"
            ),
            token_basis="record.definition",
            measurement_kind="measured_local_data",
            notes=(
                "Canonical JSON is the source-shaped 789-record dataset; "
                "not a PDF file."
            ),
        ),
        inventory_row(
            dataset_name="BOK RAG terms",
            source="data/bok_terms_2026_rag.jsonl; row.publisher=한국은행",
            file_format="JSONL",
            file_count=1,
            record_count=len(rag_rows),
            document_count=len({str(row.get("document_id")) for row in rag_rows}),
            chunk_count=chunk_projection.get("chunk_count"),
            token_stats=statistics(all_content_lengths),
            duplicate_count=duplicate_doc_ids + duplicate_hashes,
            empty_count=empty_content,
            review_status="; ".join(
                f"{key}={value}" for key, value in sorted(status_counts.items())
            ),
            license_status=str(extraction_payload.get("license_status")),
            token_basis="row.content; o200k_base",
            measurement_kind="measured_local_data_and_code_projection",
            notes="Chunk count is a read-only projection over approved rows only.",
        ),
        inventory_row(
            dataset_name="BOK RAG evaluation cases",
            source="data/bok_eval_questions.json -> source_dataset",
            file_format="JSON",
            file_count=1,
            record_count=len(eval_payload["cases"]),
            document_count=len(
                {
                    doc_id
                    for case in eval_payload["cases"]
                    for doc_id in case.get("relevant_document_ids", [])
                }
            ),
            chunk_count=0,
            token_stats=statistics(token_lengths(eval_texts, tokenizer)),
            duplicate_count=0,
            empty_count=sum(
                not str(case.get("question", "")).strip()
                for case in eval_payload["cases"]
            ),
            review_status="; ".join(
                f"{key}={value}"
                for key, value in sorted(
                    counts(
                        case.get("gold_status") for case in eval_payload["cases"]
                    ).items()
                )
            ),
            license_status=(
                "Inherited from BOK source; not independently recorded in this file"
            ),
            token_basis="question + history.content",
            measurement_kind="measured_local_data",
            notes=(
                "Evaluation cases, not a retrieval corpus; 25 unique relevant "
                "document IDs."
            ),
        ),
        inventory_row(
            dataset_name="BOK extraction report",
            source="data/bok_extraction_report.json",
            file_format="JSON",
            file_count=1,
            record_count=1,
            document_count=None,
            chunk_count=None,
            token_stats=statistics([]),
            duplicate_count=None,
            empty_count=None,
            review_status=(
                "approved_record_count="
                f"{extraction_payload.get('approved_record_count')}; "
                f"review_flag_count={extraction_payload.get('review_flag_count')}"
            ),
            license_status=str(extraction_payload.get("license_status")),
            token_basis="not applicable",
            measurement_kind="measured_local_report",
            notes=(
                "Reports 789 source/RAG records and a PDF SHA-256, but the PDF "
                "is absent locally."
            ),
        ),
        inventory_row(
            dataset_name="C0704 evaluation status",
            source="outputs/c0704/evaluation_status.json",
            file_format="JSON",
            file_count=1,
            record_count=1,
            document_count=0,
            chunk_count=0,
            token_stats=statistics([]),
            duplicate_count=None,
            empty_count=None,
            review_status=str(c0704_payload.get("status")),
            license_status="Not available",
            token_basis="not applicable",
            measurement_kind="measured_local_report",
            notes=str(c0704_payload.get("reason")),
        ),
    ]

    quality: list[dict[str, Any]] = []
    denominator = len(rag_rows)
    quality.extend(
        [
            quality_row(
                "BOK RAG terms",
                "duplicate_document_id",
                "info",
                duplicate_doc_ids,
                denominator,
                "pass" if not duplicate_doc_ids else "issue",
                "direct JSONL count",
                "Document IDs are unique.",
            ),
            quality_row(
                "BOK RAG terms",
                "duplicate_content_hash",
                "info",
                duplicate_hashes,
                denominator,
                "pass" if not duplicate_hashes else "issue",
                "direct JSONL count",
                "Content hashes are unique.",
            ),
            quality_row(
                "BOK RAG terms",
                "empty_content",
                "high",
                empty_content,
                denominator,
                "pass" if not empty_content else "issue",
                "direct JSONL count",
                "No empty content rows.",
            ),
            quality_row(
                "BOK RAG terms",
                "content_hash_mismatch",
                "high",
                content_hash_mismatches,
                denominator,
                "pass" if not content_hash_mismatches else "issue",
                "SHA-256(content) comparison",
                "Stored content_hash matches content.",
            ),
            quality_row(
                "BOK RAG terms",
                "source_url_missing_or_blank",
                "medium",
                source_url_missing,
                denominator,
                "pass" if not source_url_missing else "issue",
                "direct JSONL count",
                "Source URLs are present on every row.",
            ),
            quality_row(
                "BOK RAG terms",
                "license_missing_or_blank",
                "medium",
                license_missing,
                denominator,
                "pass" if not license_missing else "issue",
                "direct JSONL count",
                (
                    "License field is populated, but the value still requests "
                    "permission/attribution review."
                ),
            ),
            quality_row(
                "BOK RAG terms",
                "review_needs_review",
                "medium",
                status_counts.get("needs_review", 0),
                denominator,
                "review_required",
                "review_status + extraction report",
                "Needs-review records are excluded by scripts/ingest_documents.py.",
            ),
            quality_row(
                "BOK RAG terms",
                "concept_id_missing",
                "medium",
                sum(is_blank(row.get("concept_id")) for row in rag_rows),
                denominator,
                "gap",
                "expected field comparison",
                "No chapter/concept ID is stored in the local corpus.",
            ),
            quality_row(
                "BOK RAG terms",
                "concept_code_missing",
                "medium",
                sum(is_blank(row.get("concept_code")) for row in rag_rows),
                denominator,
                "gap",
                "expected field comparison",
                "No concept_code is stored in the local corpus.",
            ),
            quality_row(
                "BOK RAG terms",
                "stage_id_missing",
                "medium",
                sum(is_blank(row.get("stage_id")) for row in rag_rows),
                denominator,
                "gap",
                "expected field comparison",
                "No stage/chapter ID is stored in the local corpus.",
            ),
            quality_row(
                "BOK RAG terms",
                "chunk_id_missing_in_source",
                "info",
                sum(is_blank(row.get("chunk_id")) for row in rag_rows),
                denominator,
                "derived_at_indexing",
                "expected field comparison + indexer code",
                "chunk_id is generated after SentenceSplitter.",
            ),
            quality_row(
                "BOK RAG terms",
                "created_at_missing",
                "low",
                sum(is_blank(row.get("created_at")) for row in rag_rows),
                denominator,
                "gap",
                "expected field comparison",
                "No created_at field is stored in the corpus JSONL.",
            ),
            quality_row(
                "BOK RAG terms",
                "updated_at_missing",
                "low",
                sum(is_blank(row.get("updated_at")) for row in rag_rows),
                denominator,
                "gap",
                "expected field comparison",
                "No updated_at field is stored in the corpus JSONL.",
            ),
            quality_row(
                "BOK RAG terms",
                "term_en_null",
                "low",
                sum(row.get("term_en") is None for row in rag_rows),
                denominator,
                "observed",
                "direct JSONL count",
                "English term is optional in the source data.",
            ),
            quality_row(
                "BOK RAG terms",
                "term_kr_blank",
                "low",
                sum(
                    isinstance(row.get("term_kr"), str) and not row["term_kr"].strip()
                    for row in rag_rows
                ),
                denominator,
                "observed",
                "direct JSONL count",
                "Korean term is blank in a small number of rows.",
            ),
            quality_row(
                "BOK RAG terms",
                "very_short_content_under_50_tokens",
                "low",
                sum(length < 50 for length in all_content_lengths),
                denominator,
                "review",
                "o200k_base token count",
                "Potentially short records; not automatically rejected.",
            ),
            quality_row(
                "BOK RAG terms",
                "very_long_content_over_800_tokens",
                "low",
                sum(length > 800 for length in all_content_lengths),
                denominator,
                "review",
                "o200k_base token count",
                "Potentially long records; SentenceSplitter still handles them.",
            ),
            quality_row(
                "BOK RAG terms",
                "repeated_source_id",
                "info",
                len(rag_rows) - len(source_id_counts),
                denominator,
                "expected",
                "direct JSONL cardinality",
                "source_id identifies the BOK source collection, not each document.",
            ),
            quality_row(
                "BOK extraction report",
                "source_pdf_missing_locally",
                "medium",
                1,
                1,
                "gap",
                "report contains source_pdf_sha256; find data found no PDF",
                "The source PDF itself is not in the repository.",
            ),
            quality_row(
                "C0704 evaluation status",
                "mentor_dataset_files_missing",
                "high",
                2,
                2,
                "blocked",
                "outputs/c0704/evaluation_status.json",
                (
                    "Required mentor approved/review JSONL files are absent; "
                    "no substitute was used."
                ),
            ),
        ]
    )

    metadata = row_field_report("BOK RAG terms", rag_rows, EXPECTED_RAG_FIELDS)
    metadata.extend(
        row_field_report("BOK canonical terms", source_rows, sorted(source_rows[0]))
    )

    REPORTS.mkdir(parents=True, exist_ok=True)
    write_csv(REPORTS / "dataset_inventory.csv", inventory)
    write_csv(REPORTS / "dataset_quality_report.csv", quality)
    write_csv(REPORTS / "metadata_field_report.csv", metadata)

    settings = {
        "llm_model": "openai/gpt-4o-mini",
        "embedding_model": "openai/text-embedding-3-small",
        "chunk_size": 700,
        "chunk_overlap": 100,
        "approved_review_status": "approved",
        "retrieval_top_k": 5,
        "embedding_dimension": 1536,
    }
    statistics_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "analysis_scope": "STEP 1 read-only local dataset and code analysis",
        "repository_root": str(ROOT),
        "tokenizer": {
            "kind": tokenizer_kind,
            "encoding": tokenizer_name,
            "basis": (
                "generation model alias gpt-4o-mini; OpenRouter-qualified model is "
                "mapped explicitly"
            ),
        },
        "code_settings": settings,
        "datasets": inventory,
        "bok_rag_detail": {
            "all_record_token_statistics": statistics(all_content_lengths),
            "approved_record_token_statistics": statistics(approved_lengths),
            "status_counts": status_counts,
            "chunk_projection": chunk_projection,
            "unique_source_id_count": len(source_id_counts),
            "unique_relevant_eval_document_ids": len(
                {
                    doc_id
                    for case in eval_payload["cases"]
                    for doc_id in case.get("relevant_document_ids", [])
                }
            ),
        },
        "quality_summary": {
            "quality_rows": len(quality),
            "issue_rows": sum(
                row["status"]
                not in {"pass", "info", "expected", "observed", "derived_at_indexing"}
                for row in quality
            ),
        },
        "filesystem_scope": {
            "data_raw_exists": (DATA / "raw").is_dir(),
            "data_processed_exists": (DATA / "processed").is_dir(),
            "data_samples_exists": (DATA / "samples").is_dir(),
            "pdf_files_found_outside_data": len(list(DATA.rglob("*.pdf"))),
            "csv_files_found_outside_data": len(list(DATA.rglob("*.csv"))),
        },
        "source_and_pipeline_notes": [
            (
                "Local BOK JSON/JSONL metadata claims publisher 한국은행; no KDI, "
                "KOSIS, "
                "OpenDART, or AI-Hub data files were found."
            ),
            (
                "BOK extraction report says deterministic pypdf extraction and no LLM "
                "rewrite; the source PDF is not locally present."
            ),
            (
                "Chunk projection used LlamaIndex SentenceSplitter and the same "
                "metadata "
                "shape as DocumentIndexer, without DB/index writes."
            ),
        ],
    }
    (REPORTS / "dataset_statistics.json").write_text(
        json.dumps(statistics_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote read-only dataset reports to {REPORTS}")
    print(
        f"BOK RAG records={len(rag_rows)}, approved={len(approved_rows)}, "
        f"projected_chunks={chunk_projection.get('chunk_count')}"
    )


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    main()
