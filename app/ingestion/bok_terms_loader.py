from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from app.rag.llamaindex.indexer import IngestDocument

REQUIRED_FIELDS = {
    "id",
    "document_id",
    "source_id",
    "document_version",
    "term",
    "definition",
    "content",
    "publisher",
    "document",
    "edition",
    "printed_page",
    "related_terms",
    "review_flags",
    "review_status",
    "source_url",
    "license",
    "content_hash",
}


class BOKDatasetValidationError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BOKDatasetValidation:
    source_count: int
    rag_count: int
    duplicate_ids: tuple[str, ...]
    missing_in_rag: tuple[str, ...]
    missing_in_source: tuple[str, ...]
    review_count: int
    approved_count: int


def _read_source(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload.get("records") if isinstance(payload, dict) else payload
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise BOKDatasetValidationError("BOK source JSON must contain a records list")
    return rows


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise BOKDatasetValidationError(
                f"invalid JSONL at {path}:{line_number}: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise BOKDatasetValidationError(
                f"BOK JSONL row {line_number} must be an object"
            )
        missing = sorted(REQUIRED_FIELDS - row.keys())
        if missing:
            raise BOKDatasetValidationError(
                f"BOK JSONL row {line_number} is missing: {', '.join(missing)}"
            )
        rows.append(row)
    return rows


def _duplicates(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for value in values:
        if value in seen:
            duplicates.add(value)
        seen.add(value)
    return tuple(sorted(duplicates))


def validate_bok_dataset(
    source_path: Path,
    rag_path: Path,
) -> BOKDatasetValidation:
    source_rows = _read_source(source_path)
    rag_rows = _read_jsonl(rag_path)
    source_ids = [str(row.get("id", "")) for row in source_rows]
    rag_ids = [str(row.get("id", "")) for row in rag_rows]
    duplicates = tuple(sorted(set(_duplicates(source_ids)) | set(_duplicates(rag_ids))))
    missing_in_rag = tuple(sorted(set(source_ids) - set(rag_ids)))
    missing_in_source = tuple(sorted(set(rag_ids) - set(source_ids)))
    errors: list[str] = []
    if duplicates:
        errors.append("duplicate IDs: " + ", ".join(duplicates))
    if missing_in_rag:
        errors.append("missing in RAG JSONL: " + ", ".join(missing_in_rag))
    if missing_in_source:
        errors.append("missing in source JSON: " + ", ".join(missing_in_source))
    if source_ids != rag_ids:
        errors.append("source JSON and RAG JSONL ID order differs")

    source_by_id = {str(row["id"]): row for row in source_rows if row.get("id")}
    review_count = 0
    approved_count = 0
    comparable = (
        "term",
        "definition",
        "publisher",
        "document",
        "edition",
        "printed_page",
        "related_terms",
        "review_flags",
    )
    for position, row in enumerate(rag_rows, 1):
        row_id = str(row["id"])
        if str(row["document_id"]) != row_id:
            errors.append(f"{row_id}: document_id must preserve the source ID")
        flags = row.get("review_flags")
        if not isinstance(flags, list):
            errors.append(f"{row_id}: review_flags must be a list")
            flags = []
        if flags:
            review_count += 1
            if row.get("review_status") == "approved":
                errors.append(f"{row_id}: flagged records cannot be approved")
        elif row.get("review_status") == "approved":
            approved_count += 1
        expected_hash = hashlib.sha256(str(row["content"]).encode("utf-8")).hexdigest()
        if row.get("content_hash") != expected_hash:
            errors.append(f"{row_id}: content_hash mismatch")
        source = source_by_id.get(row_id)
        if source is None:
            continue
        differing = [key for key in comparable if source.get(key) != row.get(key)]
        if differing:
            errors.append(f"{row_id}: source/RAG mismatch: {', '.join(differing)}")
        if not str(row.get("definition", "")).strip():
            errors.append(f"{row_id}: empty definition at row {position}")
        if int(row.get("printed_page", 0)) <= 0:
            errors.append(f"{row_id}: printed_page must be positive")

    if errors:
        preview = "; ".join(errors[:20])
        suffix = f"; and {len(errors) - 20} more" if len(errors) > 20 else ""
        raise BOKDatasetValidationError(preview + suffix)
    return BOKDatasetValidation(
        source_count=len(source_rows),
        rag_count=len(rag_rows),
        duplicate_ids=duplicates,
        missing_in_rag=missing_in_rag,
        missing_in_source=missing_in_source,
        review_count=review_count,
        approved_count=approved_count,
    )


def load_bok_terms(
    rag_path: Path,
    source_path: Path | None = None,
    approved_only: bool = True,
) -> list[IngestDocument]:
    if source_path is not None:
        validate_bok_dataset(source_path, rag_path)
    rows = _read_jsonl(rag_path)
    documents: list[IngestDocument] = []
    for row in rows:
        if approved_only and row["review_status"] != "approved":
            continue
        documents.append(
            IngestDocument(
                document_id=str(row["document_id"]),
                title=str(row["title"]),
                source=str(row["source_url"]),
                content=str(row["content"]),
                version=str(row["document_version"]),
                source_id=str(row["source_id"]),
                source_url=str(row["source_url"]),
                review_status=str(row["review_status"]),
                published_at=DocumentDate.parse(row.get("published_at")),
                license=str(row["license"]),
                content_hash=str(row["content_hash"]),
                term=str(row["term"]),
                term_kr=str(row.get("term_kr") or "") or None,
                term_en=str(row.get("term_en") or "") or None,
                publisher=str(row["publisher"]),
                document_name=str(row["document"]),
                edition=str(row["edition"]),
                printed_page=int(row["printed_page"]),
                related_terms=[str(value) for value in row["related_terms"]],
                review_flags=list(row["review_flags"]),
                knowledge_scope="global",
            )
        )
    return documents


class DocumentDate:
    @staticmethod
    def parse(value):
        from datetime import datetime

        if not value or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class BOKTermCatalog:
    """Read-only canonical term catalog used by the hybrid retrieval policy."""

    def __init__(self, rag_path: Path, approved_status: str = "approved"):
        self.rag_path = rag_path
        self.approved_status = approved_status
        self._aliases: list[tuple[str, str]] | None = None

    def match(self, query: str, limit: int = 3) -> list[str]:
        normalized_query = self._normalize(query)
        candidates = [
            (alias, term)
            for alias, term in self._load_aliases()
            if alias and alias in normalized_query
        ]
        candidates.sort(key=lambda item: len(item[0]), reverse=True)
        selected: list[tuple[str, str]] = []
        for alias, term in candidates:
            already_selected = any(
                alias in chosen_alias or term == chosen_term
                for chosen_alias, chosen_term in selected
            )
            if already_selected:
                continue
            selected.append((alias, term))
            if len(selected) >= limit:
                break
        return [term for _, term in selected]

    def _load_aliases(self) -> list[tuple[str, str]]:
        if self._aliases is not None:
            return self._aliases
        aliases: dict[tuple[str, str], None] = {}
        for row in _read_jsonl(self.rag_path):
            if row["review_status"] != self.approved_status:
                continue
            term = str(row["term"])
            for value in (term, row.get("term_kr"), row.get("term_en")):
                normalized = self._normalize(str(value or ""))
                if len(normalized) >= 2:
                    aliases[(normalized, term)] = None
        self._aliases = list(aliases)
        return self._aliases

    @staticmethod
    def _normalize(value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold()
        return re.sub(r"[^0-9a-z가-힣]+", "", value)
