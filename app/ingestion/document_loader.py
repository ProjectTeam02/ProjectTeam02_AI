from __future__ import annotations

import json
import re
from pathlib import Path

from app.rag.llamaindex.indexer import DocumentIndexer, IngestDocument


def clean_text(text: str) -> str:
    """Apply conservative cleanup without changing financial meaning."""
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    normalized = "\n".join(line.rstrip() for line in normalized.splitlines())
    return re.sub(r"\n{3,}", "\n\n", normalized).strip()


def load_manifest(manifest_path: Path) -> list[IngestDocument]:
    """Load explicitly reviewed local documents from a JSON manifest.

    The manifest has a top-level ``documents`` list. Each item references a
    UTF-8 ``.md``/``.txt`` path relative to the manifest and contains the RAG
    metadata fields. No network request is made by this loader.
    """
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    rows = payload.get("documents")
    if not isinstance(rows, list):
        raise ValueError("manifest must contain a documents list")

    documents: list[IngestDocument] = []
    required = {
        "path",
        "source_id",
        "document_id",
        "document_version",
        "title",
        "source_url",
        "review_status",
        "license",
    }
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"manifest documents[{position}] must be an object")
        missing = sorted(required - row.keys())
        if missing:
            raise ValueError(
                f"manifest documents[{position}] is missing: {', '.join(missing)}"
            )
        path = (manifest_path.parent / str(row["path"])).resolve()
        try:
            path.relative_to(manifest_path.parent.resolve())
        except ValueError as exc:
            raise ValueError(
                "document paths must stay inside the manifest directory"
            ) from exc
        if path.suffix.lower() not in {".txt", ".md"} or not path.is_file():
            raise ValueError(f"document does not exist or is not .txt/.md: {path}")
        values = dict(row)
        values.pop("path")
        values["source"] = values["source_url"]
        values["content"] = clean_text(path.read_text(encoding="utf-8"))
        if not values["content"]:
            raise ValueError(f"document is empty after cleaning: {path}")
        documents.append(DocumentIndexer._normalize(values))
    return documents


def discover_documents(
    root: Path,
    source: str,
    version: str | None,
    review_status: str,
    source_id: str | None = None,
    source_url: str | None = None,
    license_name: str | None = None,
    concept_id: str | None = None,
    stage_id: str | None = None,
) -> list[IngestDocument]:
    """Compatibility loader for one approved source shared by local files."""
    documents = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
            continue
        content = clean_text(path.read_text(encoding="utf-8"))
        if content:
            relative_id = path.relative_to(root).as_posix()
            documents.append(
                IngestDocument(
                    document_id=relative_id,
                    title=path.stem,
                    source=source,
                    source_id=source_id or source,
                    source_url=source_url or source,
                    content=content,
                    version=version,
                    review_status=review_status,
                    license=license_name,
                    concept_id=concept_id,
                    stage_id=stage_id,
                )
            )
    return documents
