# 파일 역할: 경제·금융 데이터의 정규화, 청크, 키워드, 분류 전처리를 담당합니다.
"""Dataset discovery, duplicate-aware loading, and source normalization.

The repository contains JSON and JSONL exports of the same source records.  A
canonical file is selected per institution, while the alternate export is
compared and reported instead of being counted as a second corpus.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class NormalizedDocument:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    source: str
    document_id: str
    title: str
    content: str
    source_url: str | None
    source_locator: str | None
    source_name: str | None
    source_version: str | None
    source_review_status: str
    license_status: str
    text_hash: str
    related_terms: tuple[str, ...]
    raw_file: str

    def as_dict(self) -> dict[str, Any]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        return asdict(self)


def sha256_bytes(value: bytes) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return sha256_bytes(value.encode("utf-8"))


def source_for_path(path: Path) -> str | None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    name = path.name.casefold()
    parent = str(path.parent).casefold()
    if "kdi" in name or "kdi" in parent:
        return "KDI"
    if "bok" in name or "한국은행" in parent:
        return "BOK"
    return None


def discover_dataset_files(data_dir: Path) -> list[Path]:
    """Find only the named source exports, never reports or arbitrary JSON."""
    paths: list[Path] = []
    for path in sorted(data_dir.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".json", ".jsonl"}:
            continue
        if source_for_path(path) is not None and "term" in path.name.casefold():
            paths.append(path)
    return paths


def read_records(path: Path) -> list[dict[str, Any]]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if path.suffix.lower() == ".jsonl":
        rows: list[dict[str, Any]] = []
        for line_number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not line.strip():
                continue
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"{path}:{line_number} must be a JSON object")
            rows.append(value)
        return rows

    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict) and isinstance(payload.get("records"), list):
        rows = payload["records"]
    else:
        raise ValueError(f"{path} must contain a list or a records list")
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"{path} contains a non-object record")
    return rows


def _text(value: Any) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return "" if value is None else str(value).strip()


def _source_value(row: dict[str, Any], key: str) -> Any:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    nested = row.get("source")
    if isinstance(nested, dict):
        return nested.get(key)
    metadata = row.get("metadata")
    if isinstance(metadata, dict):
        return metadata.get(key)
    return None


def normalize_record(
    source: str, row: dict[str, Any], path: Path
) -> NormalizedDocument:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
    nested_source = row.get("source") if isinstance(row.get("source"), dict) else {}
    document_id = _text(row.get("document_id") or row.get("id"))
    if not document_id:
        raise ValueError(f"{path} contains a record without id")

    if source == "BOK":
        content = _text(row.get("text") or row.get("content") or row.get("definition"))
        title = _text(
            row.get("title")
            or metadata.get("term")
            or row.get("term")
            or row.get("term_kr")
        )
        source_name = _text(
            metadata.get("publisher") or nested_source.get("publisher") or "한국은행"
        )
        source_version = (
            _text(metadata.get("edition") or nested_source.get("edition")) or None
        )
        page = metadata.get("printed_page", nested_source.get("printed_page"))
        pdf_start = metadata.get("pdf_page_start", nested_source.get("pdf_page_start"))
        pdf_end = metadata.get("pdf_page_end", nested_source.get("pdf_page_end"))
        locator_parts = []
        if page is not None:
            locator_parts.append(f"printed_page={page}")
        if pdf_start is not None:
            locator_parts.append(f"pdf_page_start={pdf_start}")
        if pdf_end is not None:
            locator_parts.append(f"pdf_page_end={pdf_end}")
        source_locator = ", ".join(locator_parts) or None
        related = metadata.get("related_terms", row.get("related_terms", []))
        source_url = _text(
            metadata.get("source_url") or nested_source.get("source_url")
        )
    else:
        content = _text(row.get("content") or row.get("definition") or row.get("text"))
        title = _text(row.get("title") or row.get("term"))
        source_name = _text(row.get("source")) or "KDI"
        source_version = _text(row.get("retrieved_at")) or None
        source_url = _text(row.get("source_url")) or None
        source_locator = f"dic_idx={row['dic_idx']}" if row.get("dic_idx") else None
        related = row.get("related_terms", [])

    if not content:
        raise ValueError(f"{path} record {document_id} has empty content")
    related_terms = tuple(_text(item) for item in related if _text(item))
    return NormalizedDocument(
        source=source,
        document_id=document_id,
        title=title or document_id,
        content=content,
        source_url=source_url,
        source_locator=source_locator,
        source_name=source_name or None,
        source_version=source_version,
        source_review_status=_text(
            row.get("review_status") or metadata.get("review_status") or "UNKNOWN"
        ),
        license_status=_text(
            row.get("license") or metadata.get("license") or "UNCONFIRMED"
        ),
        text_hash=sha256_text(content),
        related_terms=related_terms,
        raw_file=str(path),
    )


def _record_identity(row: dict[str, Any]) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return _text(row.get("document_id") or row.get("id"))


def _record_content(source: str, row: dict[str, Any]) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    content = _text(row.get("text") or row.get("content") or row.get("definition"))
    if source == "BOK" and "설명:" in content:
        return content.split("설명:", 1)[1].strip()
    return content


def _canonical_path(paths: Iterable[Path]) -> Path:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    ordered = sorted(paths, key=lambda p: (p.suffix.lower() != ".jsonl", str(p)))
    return ordered[0]


def load_corpus(data_dir: Path) -> tuple[list[NormalizedDocument], dict[str, Any]]:
    """Load one canonical export per source and return an audit inventory."""
    files = discover_dataset_files(data_dir)
    if not files:
        raise FileNotFoundError(
            "No dataset exports found. Place the KDI and BOK JSON/JSONL files "
            "under data/ and check data/README.md."
        )
    grouped: dict[str, list[Path]] = {}
    for path in files:
        source = source_for_path(path)
        if source is not None:
            grouped.setdefault(source, []).append(path)

    documents: list[NormalizedDocument] = []
    file_inventory: list[dict[str, Any]] = []
    duplicate_audit: list[dict[str, Any]] = []
    for source in sorted(grouped):
        source_paths = grouped[source]
        canonical = _canonical_path(source_paths)
        canonical_rows = read_records(canonical)
        documents.extend(
            normalize_record(source, row, canonical) for row in canonical_rows
        )
        canonical_by_id = {
            _record_identity(row): sha256_text(_record_content(source, row))
            for row in canonical_rows
        }
        for path in source_paths:
            rows = read_records(path)
            file_inventory.append(
                {
                    "source": source,
                    "path": str(path),
                    "format": path.suffix.lower().lstrip("."),
                    "record_count": len(rows),
                    "file_sha256": sha256_bytes(path.read_bytes()),
                    "is_canonical": path == canonical,
                }
            )
            if path == canonical:
                continue
            alternate_by_id = {
                _record_identity(row): sha256_text(_record_content(source, row))
                for row in rows
            }
            duplicate_audit.append(
                {
                    "source": source,
                    "canonical_file": str(canonical),
                    "alternate_file": str(path),
                    "canonical_records": len(canonical_by_id),
                    "alternate_records": len(alternate_by_id),
                    "same_id_count": len(set(canonical_by_id) & set(alternate_by_id)),
                    "same_id_and_content_count": sum(
                        canonical_by_id.get(key) == value
                        for key, value in alternate_by_id.items()
                        if key in canonical_by_id
                    ),
                    "id_only_mismatch_count": len(
                        set(canonical_by_id) ^ set(alternate_by_id)
                    ),
                }
            )

    documents.sort(key=lambda item: (item.source, item.document_id))
    by_source = {
        source: sum(document.source == source for document in documents)
        for source in sorted({document.source for document in documents})
    }
    corpus_version = sha256_text(
        "|".join(
            f"{item.source}:{item.document_id}:{item.text_hash}" for item in documents
        )
    )
    inventory = {
        "data_dir": str(data_dir),
        "file_count": len(file_inventory),
        "files": file_inventory,
        "duplicate_audit": duplicate_audit,
        "document_count": len(documents),
        "document_count_by_source": by_source,
        "cross_source_same_content_count": _cross_source_same_content_count(documents),
        "dataset_version": corpus_version,
        "canonical_counting_rule": (
            "JSONL is canonical when both JSON and JSONL exist for a source; "
            "the alternate export is audit-only. Cross-source records are not merged."
        ),
    }
    return documents, inventory


def _cross_source_same_content_count(documents: list[NormalizedDocument]) -> int:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    hashes_by_source: dict[str, set[str]] = {}
    for document in documents:
        hashes_by_source.setdefault(document.source, set()).add(document.text_hash)
    sources = sorted(hashes_by_source)
    return sum(
        len(hashes_by_source[left] & hashes_by_source[right])
        for index, left in enumerate(sources)
        for right in sources[index + 1 :]
    )
