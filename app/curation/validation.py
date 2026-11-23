"""Reproducible validation for the 2026-11-23 economic curation drop."""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

EXPECTED_FILES = {
    "concept_master": "concept/concept_master.json",
    "concept_master_1123": "concept/concept_master_1123.json",
    "concept_check": "concept/concept_check.txt",
    "bok_documents_raw": "source/bok_documents_raw.csv",
    "bok_documents": "source/bok_documents.csv",
    "concept_source_candidates": "source/concept_source_candidates.csv",
    "concept_sources_reviewed": "source/concept_sources_reviewed.csv",
    "source_check": "source/source_check.txt",
    "source_check_after": "source/source_check_after.txt",
    "prerequisite_raw": "prerequisite/prerequisite_raw.csv",
    "prerequisite_review": "prerequisite/prerequisite_review.csv",
    "ai_schema_check": "db_check/ai_schema_check.txt",
}

EXPECTED_COUNTS = {
    "concepts": 29,
    "bok_documents": 760,
    "source_linked_concepts": 17,
    "concept_document_relations": 25,
    "source_unlinked_concepts": 12,
    "prerequisite_relations": 26,
    "ai_schema_passes": 17,
}

APPROVED = {"approved", "cleared", "verified"}


def _value(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _records(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _json_records(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = next(
            (payload[key] for key in ("concepts", "records", "items", "data")
             if isinstance(payload.get(key), list)),
            [],
        )
    else:
        rows = []
    return [row for row in rows if isinstance(row, dict)]


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig")


def _concept_code(row: dict[str, Any]) -> str:
    return _value(row, "conceptCode", "concept_code", "code")


def _document_id(row: dict[str, Any]) -> str:
    return _value(row, "documentId", "document_id", "id", "sourceDocumentId")


def _status(row: dict[str, Any], *names: str) -> str:
    return _value(row, *names).casefold()


def _duplicates(values: Iterable[str]) -> list[str]:
    counts = Counter(value for value in values if value)
    return sorted(value for value, count in counts.items() if count > 1)


def _cycles(edges: Iterable[tuple[str, str]]) -> list[list[str]]:
    graph: dict[str, set[str]] = defaultdict(set)
    for left, right in edges:
        graph[left].add(right)
    state: dict[str, int] = {}
    stack: list[str] = []
    found: list[list[str]] = []

    def visit(node: str) -> None:
        state[node] = 1
        stack.append(node)
        for target in sorted(graph.get(node, set())):
            if state.get(target, 0) == 0:
                visit(target)
            elif state.get(target) == 1 and target in stack:
                start = stack.index(target)
                found.append(stack[start:] + [target])
        stack.pop()
        state[node] = 2

    for node in sorted(graph):
        if state.get(node, 0) == 0:
            visit(node)
    return found


def validate_curation(root: Path) -> dict[str, Any]:
    """Validate supplied exports without changing any source or DB data."""

    paths = {name: root / relative for name, relative in EXPECTED_FILES.items()}
    missing = [
        relative
        for name, relative in EXPECTED_FILES.items()
        if not paths[name].is_file()
    ]
    report: dict[str, Any] = {
        "schemaVersion": 1,
        "status": "BLOCKED" if missing else "READY",
        "inputRoot": str(root),
        "expectedFiles": EXPECTED_FILES,
        "missingFiles": missing,
        "errors": [],
        "warnings": [],
        "counts": {},
        "approval": {
            "publishedConceptsMissingReviewHistory": [],
            "pendingLicenseDocuments": [],
            "approvedPrerequisiteRowsAreNotDbApproval": True,
        },
    }
    if missing:
        report["errors"].append("required curation files are missing")
        return report

    try:
        concepts = _json_records(paths["concept_master_1123"])
        concepts_base = _json_records(paths["concept_master"])
        documents = _records(paths["bok_documents"])
        documents_raw = _records(paths["bok_documents_raw"])
        candidates = _records(paths["concept_source_candidates"])
        reviewed = _records(paths["concept_sources_reviewed"])
        prerequisite_raw = _records(paths["prerequisite_raw"])
        prerequisite_review = _records(paths["prerequisite_review"])
    except (OSError, UnicodeError, json.JSONDecodeError, csv.Error) as exc:
        report["errors"].append(f"input parse failed: {type(exc).__name__}: {exc}")
        return report

    concept_codes = [_concept_code(row) for row in concepts]
    document_ids = [_document_id(row) for row in documents]
    report["counts"].update({
        "concepts": len(concepts),
        "concept_master_base": len(concepts_base),
        "bok_documents": len(documents),
        "bok_documents_raw": len(documents_raw),
        "source_candidates": len(candidates),
        "source_reviewed": len(reviewed),
        "prerequisite_raw": len(prerequisite_raw),
        "prerequisite_review": len(prerequisite_review),
        "ai_schema_passes": sum(
            line.strip().casefold() == "pass"
            or " pass" in line.casefold()
            for line in _text(paths["ai_schema_check"]).splitlines()
        ),
    })
    duplicate_concepts = _duplicates(concept_codes)
    if duplicate_concepts:
        report["errors"].append(f"duplicate concept codes: {duplicate_concepts}")
    duplicate_documents = _duplicates(document_ids)
    if duplicate_documents:
        report["errors"].append(f"duplicate document ids: {duplicate_documents}")
    if len(set(concept_codes)) != len(concepts):
        report["errors"].append("one or more concepts have missing conceptCode")
    if len(set(document_ids)) != len(documents):
        report["errors"].append("one or more documents have missing documentId")

    published_without_review = [
        _concept_code(row) for row in concepts
        if _status(row, "status", "conceptStatus") == "published"
        and (
            not _value(row, "reviewedBy", "reviewed_by")
            or not _value(row, "reviewedAt", "reviewed_at")
        )
    ]
    report["approval"]["publishedConceptsMissingReviewHistory"] = (
        published_without_review
    )
    if published_without_review:
        report["errors"].append("PUBLISHED concepts are missing review history")

    by_document = set(document_ids)
    reviewed_relations = []
    for row in reviewed:
        code = _concept_code(row)
        document_id = _document_id(row)
        if code and code not in set(concept_codes):
            report["errors"].append(
                f"source relation references unknown concept: {code}"
            )
        if document_id and document_id not in by_document:
            report["errors"].append(
                f"source relation references unknown document: {document_id}"
            )
        if code and document_id:
            reviewed_relations.append((code, document_id))
        license_status = _status(row, "licenseReviewStatus", "license_review_status")
        if license_status not in APPROVED and license_status:
            report["approval"]["pendingLicenseDocuments"].append(document_id)

    prereq_edges: list[tuple[str, str]] = []
    for row in prerequisite_review:
        code = _concept_code(row)
        prerequisite = _value(
            row,
            "prerequisiteConceptCode",
            "prerequisite_concept_code",
            "prerequisiteCode",
        )
        if code == prerequisite and code:
            report["errors"].append(f"self prerequisite: {code}")
        if code and prerequisite:
            prereq_edges.append((code, prerequisite))
        if _status(row, "decision", "reviewStatus", "review_status") == "approved":
            report["warnings"].append(
                "CSV prerequisite APPROVED is not treated as DB approval without "
                "review history"
            )
    duplicate_edges = _duplicates(f"{left}->{right}" for left, right in prereq_edges)
    if duplicate_edges:
        report["errors"].append(f"duplicate prerequisite relations: {duplicate_edges}")
    cycles = _cycles(prereq_edges)
    if cycles:
        report["errors"].append(f"prerequisite cycles: {cycles}")

    linked_codes = {code for code, _ in reviewed_relations}
    report["counts"].update({
        "source_linked_concepts": len(linked_codes),
        "concept_document_relations": len(set(reviewed_relations)),
        "source_unlinked_concepts": len(set(concept_codes) - linked_codes),
        "prerequisite_relations": len(set(prereq_edges)),
    })
    for name, expected in EXPECTED_COUNTS.items():
        actual = report["counts"].get(name)
        if actual is not None and actual != expected:
            report["warnings"].append(f"{name}: expected {expected}, found {actual}")
    if report["errors"]:
        report["status"] = "BLOCKED"
    return report


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "# 2026-11-23 경제 개념·출처·선수관계 검증 보고서",
        "",
        f"- 상태: `{report['status']}`",
        f"- 입력 루트: `{report['inputRoot']}`",
        "- 원본 데이터 수정: `False`",
        "- 자동 승인 수행: `False`",
        "",
        "## 누락 파일",
        "",
    ]
    lines.extend(f"- `{item}`" for item in report["missingFiles"] or ["없음"])
    lines.extend(["", "## 건수", ""])
    lines.extend(f"- {key}: {value}" for key, value in report["counts"].items())
    lines.extend(["", "## 오류", ""])
    lines.extend(f"- {item}" for item in report["errors"] or ["없음"])
    lines.extend(["", "## 경고 및 승인 경계", ""])
    lines.extend(f"- {item}" for item in report["warnings"] or ["없음"])
    lines.append(
        "- CSV의 APPROVED 결정은 DB 검수 이력(reviewed_by/reviewed_at) 확인 전에는 "
        "승인으로 간주하지 않는다."
    )
    return "\n".join(lines) + "\n"
