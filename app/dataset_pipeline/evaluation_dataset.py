# ruff: noqa: E501

"""Build and validate the combined KDI/BOK classification evaluation set.

This module is intentionally read-only with respect to source JSON/JSONL and
Excel workbooks.  Workbook labels are reference annotations until an
independent human Gold set is approved; a string such as ``완료`` in the
``확정 골드`` column is never converted into a numeric label.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Iterable
from xml.etree import ElementTree

from app.dataset_pipeline.evaluation import validate_relevance_score
from app.dataset_pipeline.io import NormalizedDocument, load_corpus
from app.dataset_pipeline.labels import (
    analyze_label_rows,
    normalize_filename,
    read_xlsx_rows,
)
from scripts.rebuild_precision_pipeline import _records

ROOT = Path(__file__).resolve().parents[2]
KDI_WORKBOOK_NAMES = ("라벨링(1).xlsx", "라벨링.xlsx")
BOK_WORKBOOK_NAMES = ("BOK_라벨링.xlsx",)
EXPECTED_HEADERS = (
    "번호",
    "출처",
    "원문ID",
    "용어",
    "설명",
    "글자수",
    "원문 위치",
    "원본 점검플래그",
    "청크 분할 검토",
    "자료 품질",
    "관련도 A",
    "관련도 B",
    "확정 골드",
    "문제 생성 적합",
    "튜터 검색 적합",
    "판정 근거",
    "키워드 분류",
    "샘플 추출 계층",
    "B 재검토 대상",
    "완료 상태",
    "평가용 이진 라벨",
)

_XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def text(value: object) -> str:
    """Normalize missing spreadsheet values without changing meaningful text."""
    result = "" if value is None else str(value).strip()
    return "" if result.casefold() in {"", "none", "null", "nan"} else result


def score(value: object) -> int | None:
    """Return a numeric 0/1/2 or None; never coerce status text to a score."""
    value_text = text(value)
    if not value_text:
        return None
    try:
        return validate_relevance_score(value_text)
    except ValueError:
        return None


def file_inventory(path: Path, root: Path = ROOT) -> dict[str, Any]:
    """Return auditable path, size, mtime and SHA-256 information."""
    stat = path.stat()
    try:
        display_path = str(path.relative_to(root))
    except ValueError:
        display_path = str(path)
    return {
        "path": display_path,
        "absolute_path": str(path.resolve()),
        "size_bytes": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }


def workbook_sheet_names(path: Path) -> list[str]:
    """Read worksheet names from XLSX metadata without editing the workbook."""
    with zipfile.ZipFile(path) as archive:
        workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
        relationships = ElementTree.fromstring(
            archive.read("xl/_rels/workbook.xml.rels")
        )
        targets = {
            item.attrib.get("Id"): item.attrib.get("Target", "")
            for item in relationships.findall(f"{_PKG_REL_NS}Relationship")
        }
        names: list[str] = []
        for sheet in workbook.findall(f"{_XML_NS}sheets/{_XML_NS}sheet"):
            relationship_id = sheet.attrib.get(f"{_REL_NS}id")
            names.append(
                f"{sheet.attrib.get('name', '')} ({targets.get(relationship_id, '')})"
            )
        return names


def discover_workbooks(root: Path = ROOT) -> dict[str, list[Path]]:
    """Find source-specific workbooks and preserve all candidates for auditing."""
    candidates: dict[str, list[Path]] = {"KDI": [], "BOK": []}
    kdi_names = {normalize_filename(name) for name in KDI_WORKBOOK_NAMES}
    bok_names = {normalize_filename(name) for name in BOK_WORKBOOK_NAMES}
    for path in sorted(root.rglob("*.xlsx")):
        if any(part in {".git", ".venv", "node_modules"} for part in path.parts):
            continue
        normalized = normalize_filename(path.name)
        if normalized in bok_names:
            candidates["BOK"].append(path)
        elif normalized in kdi_names:
            candidates["KDI"].append(path)
    return candidates


def resolve_workbook(
    source: str,
    path: Path | None = None,
    root: Path = ROOT,
) -> tuple[Path, dict[str, Any]]:
    """Resolve one workbook, failing on conflicting copies instead of guessing."""
    if path is not None:
        candidates = [path]
    else:
        candidates = discover_workbooks(root).get(source, [])
    if not candidates:
        names = KDI_WORKBOOK_NAMES if source == "KDI" else BOK_WORKBOOK_NAMES
        raise FileNotFoundError(f"{source} workbook not found; tried {names}")
    inventories = [file_inventory(item, root) for item in candidates]
    hashes = {item["sha256"] for item in inventories}
    if len(candidates) > 1 and len(hashes) > 1:
        raise ValueError(
            f"ambiguous {source} workbooks with different hashes: "
            f"{[item['path'] for item in inventories]}"
        )
    # Same-content copies are safe to resolve deterministically, but remain in
    # the inventory so the decision is visible in the report.
    preferred = sorted(
        candidates,
        key=lambda item: (
            not item.is_relative_to(root / "data"),
            item.name != ("BOK_라벨링.xlsx" if source == "BOK" else "라벨링(1).xlsx"),
            str(item),
        ),
    )[0]
    return preferred, {
        "source": source,
        "selected": file_inventory(preferred, root),
        "candidates": inventories,
        "candidate_count": len(candidates),
        "same_hash_for_all_candidates": len(hashes) == 1,
    }


def _normalized_content(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    normalized = re.sub(r"\s+", "", normalized)
    return normalized.casefold()


def _source_content(document: NormalizedDocument) -> str:
    """Remove the BOK JSONL presentation prefix before comparing to Excel."""
    if document.source == "BOK" and "설명:" in document.content:
        return document.content.split("설명:", 1)[1].strip()
    return document.content


def _match_type(excel: str, source: str) -> str:
    if not source:
        return "SOURCE_NOT_FOUND"
    if excel == source:
        return "EXACT_MATCH"
    if _normalized_content(excel) == _normalized_content(source):
        return "NORMALIZED_MATCH"
    return "CONTENT_MISMATCH"


def _metadata_match(excel: str, source: str, source_kind: str) -> str:
    if not source:
        return "SOURCE_NOT_FOUND"
    if source_kind == "BOK":
        return "NOT_COMPARABLE_EXTERNAL_LOCATOR"
    if excel == source:
        return "EXACT_MATCH"
    if _normalized_content(excel) == _normalized_content(source):
        return "NORMALIZED_MATCH"
    return "MISMATCH"


def _title_match_type(excel: str, source: str) -> str:
    """Treat a source title's parenthetical English alias as metadata, not a mismatch."""
    if not source:
        return "SOURCE_NOT_FOUND"
    if excel == source:
        return "EXACT_MATCH"
    if excel == source.splitlines()[0].strip():
        return "NORMALIZED_MATCH"
    return "MISMATCH"


def _extract_evidence(reason: str) -> str:
    marker = "[원문 발췌]"
    if marker in reason:
        return reason.split(marker, 1)[1].strip().splitlines()[0].strip()
    return ""


def _data_quality(record: dict[str, Any]) -> str:
    flags = [record.get("quality"), record.get("quality_flag")]
    return (
        "REVIEW_REQUIRED"
        if any(text(value) and text(value) != "정상" for value in flags)
        else "NORMAL"
    )


def _source_version(inventory: dict[str, Any]) -> str:
    return str(inventory.get("dataset_version", "UNKNOWN"))


def _normalize_workbook(
    source: str,
    path: Path,
    corpus_by_id: dict[str, NormalizedDocument],
    dataset_version: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows = read_xlsx_rows(path)
    analysis = analyze_label_rows(rows, path)
    records = _records(rows, analysis["detected_columns"])
    output: list[dict[str, Any]] = []
    reconciliation = Counter()
    for record in records:
        document = corpus_by_id.get(record["document_id"])
        source_content = _source_content(document) if document else ""
        content = text(record["content"])
        match_type = _match_type(content, source_content)
        title_match_type = _title_match_type(
            text(record["title"]), document.title if document else ""
        )
        source_locator_match = _metadata_match(
            text(record["source_locator"]),
            (document.source_url or document.source_locator or "") if document else "",
            source,
        )
        explicit = record["gold_score"]
        consensus = (
            record["reviewer_a"]
            if record["reviewer_a"] is not None
            and record["reviewer_a"] == record["reviewer_b"]
            else None
        )
        proposed = explicit if explicit is not None else consensus
        provenance = (
            "EXPLICIT_WORKBOOK_LABEL"
            if explicit is not None
            else (
                "REVIEWER_AB_CONSENSUS_PROXY"
                if consensus is not None
                else "REVIEWER_AB_DISAGREEMENT_PENDING"
            )
        )
        if document is not None:
            canonical_hash = document.text_hash
        else:
            canonical_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        reconciliation[match_type] += 1
        output.append(
            {
                "source": source,
                "document_id": record["document_id"],
                "title": record["title"],
                "content": content,
                "content_length": len(content),
                "source_locator": record["source_locator"],
                "content_hash": canonical_hash,
                "excel_content_hash": hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest(),
                "dataset_version": dataset_version,
                "chapter_id": "inflation",
                "sampling_bucket": text(
                    rows[record["row_number"] - 2].get("샘플 추출 계층", "")
                ),
                "label_a": record["reviewer_a"],
                "label_b": record["reviewer_b"],
                "explicit_workbook_gold": explicit,
                "proposed_final_label": proposed,
                "label_provenance": provenance,
                "gold_label": None,
                "gold_review_status": "NOT_INDEPENDENT_REFERENCE",
                "reason": record["reason"],
                "evidence_quote": _extract_evidence(record["reason"]),
                "data_quality_status": _data_quality(record),
                "source_match_type": match_type,
                "title_match_type": title_match_type,
                "source_locator_match": source_locator_match,
                "source_title": document.title if document else "",
                "source_content": source_content,
                "source_review_status": document.source_review_status
                if document
                else "SOURCE_NOT_FOUND",
                "source_license_status": document.license_status
                if document
                else "UNKNOWN",
                "source_url": document.source_url if document else "",
                "raw_workbook_path": str(path),
                "raw_workbook_row": record["row_number"],
                "keyword_label": record["keyword_label"],
                "quiz_suitable": record["quiz_suitable"],
                "tutor_suitable": record["tutor_suitable"],
                "b_review": record["b_review"],
                "original_quality_flag": record["quality_flag"],
                "chunk_review": text(
                    rows[record["row_number"] - 2].get("청크 분할 검토", "")
                ),
            }
        )
    return output, {
        "source": source,
        "workbook_path": str(path),
        "row_count": len(rows),
        "column_count": len(rows[0]) if rows else 0,
        "headers": list(rows[0]) if rows else [],
        "expected_headers_missing": sorted(
            set(EXPECTED_HEADERS) - set(rows[0] if rows else [])
        ),
        "detected_columns": analysis["detected_columns"],
        "validation": analysis,
        "reconciliation_counts": dict(reconciliation),
        "explicit_gold_numeric_count": sum(
            row["explicit_workbook_gold"] is not None for row in output
        ),
        "explicit_gold_nonnumeric_values": dict(
            Counter(
                text(rows[index].get("확정 골드", ""))
                for index in range(len(rows))
                if score(rows[index].get("확정 골드", "")) is None
                and text(rows[index].get("확정 골드", ""))
            )
        ),
    }


def _cross_source_duplicate_ids(rows: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    by_id: dict[str, set[str]] = {}
    for row in rows:
        by_id.setdefault(row["document_id"], set()).add(row["source"])
    return {key: sorted(value) for key, value in by_id.items() if len(value) > 1}


def build_combined_dataset(
    data_dir: Path = ROOT / "data",
    kdi_workbook: Path | None = None,
    bok_workbook: Path | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Load canonical corpus, validate both workbooks and return 320-style rows."""
    corpus, corpus_inventory = load_corpus(data_dir)
    corpus_by_id = {document.document_id: document for document in corpus}
    resolved: dict[str, dict[str, Any]] = {}
    paths: dict[str, Path] = {}
    for source, supplied in (("KDI", kdi_workbook), ("BOK", bok_workbook)):
        path, info = resolve_workbook(source, supplied)
        paths[source] = path
        resolved[source] = {**info, "sheet_names": workbook_sheet_names(path)}
    rows: list[dict[str, Any]] = []
    source_reports: dict[str, Any] = {}
    for source in ("KDI", "BOK"):
        source_rows, source_report = _normalize_workbook(
            source,
            paths[source],
            corpus_by_id,
            _source_version(corpus_inventory),
        )
        rows.extend(source_rows)
        source_reports[source] = source_report
    id_counts = Counter(row["document_id"] for row in rows)
    duplicate_ids = sorted(key for key, count in id_counts.items() if count > 1)
    invalid_ids = [
        row["document_id"]
        for row in rows
        if not row["document_id"]
        or not re.match(r"^(kdi_dic_\d+|bok2026-\d+)$", row["document_id"])
    ]
    summary = {
        "status": "EXECUTED_READ_ONLY",
        "expected_row_count": 320,
        "combined_row_count": len(rows),
        "source_row_counts": dict(Counter(row["source"] for row in rows)),
        "duplicate_document_ids": duplicate_ids,
        "cross_source_duplicate_ids": _cross_source_duplicate_ids(rows),
        "invalid_document_ids": sorted(set(invalid_ids)),
        "corpus_inventory": corpus_inventory,
        "workbooks": resolved,
        "source_reports": source_reports,
        "dataset_version": corpus_inventory["dataset_version"],
        "independent_gold_count": 0,
        "gold_status": "NOT_READY",
        "gold_policy": "Workbook labels and A/B consensus are reference/proxy only; no independent Gold was created.",
    }
    return rows, summary


def cohen_kappa(rows: Iterable[dict[str, Any]], left: str, right: str) -> float | None:
    """Calculate Cohen's kappa; return None when no comparable labels exist."""
    values = [
        (row.get(left), row.get(right))
        for row in rows
        if row.get(left) in {0, 1, 2} and row.get(right) in {0, 1, 2}
    ]
    if not values:
        return None
    total = len(values)
    observed = (
        sum(left_value == right_value for left_value, right_value in values) / total
    )
    left_counts = Counter(value[0] for value in values)
    right_counts = Counter(value[1] for value in values)
    expected = sum(left_counts[label] * right_counts[label] for label in range(3)) / (
        total * total
    )
    if expected == 1:
        return 1.0
    return (observed - expected) / (1 - expected)


def label_agreement_report(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize A/B agreement while explicitly avoiding a human-rater claim."""
    by_source: dict[str, Any] = {}
    for source in ("KDI", "BOK", "ALL"):
        subset = (
            rows
            if source == "ALL"
            else [row for row in rows if row["source"] == source]
        )
        comparable = [
            row
            for row in subset
            if row["label_a"] is not None and row["label_b"] is not None
        ]
        agree = sum(row["label_a"] == row["label_b"] for row in comparable)
        by_source[source] = {
            "comparable_count": len(comparable),
            "agree_count": agree,
            "disagree_count": len(comparable) - agree,
            "agreement_rate": agree / len(comparable) if comparable else None,
            "cohen_kappa": cohen_kappa(subset, "label_a", "label_b"),
            "interpretation": "AI_REVIEW_AGREEMENT; reviewer identity/type is not independently verified",
        }
    return {
        "status": "EXECUTED_REFERENCE_LABEL_AUDIT",
        "by_source": by_source,
        "human_inter_rater_agreement_status": "NOT_COMPUTED_REVIEWER_PROVENANCE_MISSING",
        "note": "A/B agreement and kappa are descriptive workbook checks, not verified human inter-rater reliability.",
    }
