# 파일 역할: 라벨링 XLSX를 의존성 없이 읽고 품질 검사를 수행합니다.
"""Label workbook validation with a small, read-only XLSX reader.

The project intentionally does not add an Excel editing dependency.  This
module reads the first worksheet from a normal `.xlsx` workbook using Python's
standard library, then performs schema-aware checks.  Legacy `.xls` files are
reported as unsupported instead of being guessed at.
"""

from __future__ import annotations

import math
import re
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

LABEL_CANDIDATE_NAMES = ("라벨링.xlsx", "labeling.xlsx", "labels.xlsx")
MANUAL_REVIEW_TERMS = (
    "기준금리",
    "상품권",
    "생산자물가지수",
    "국제피셔효과",
    "차이메리카",
    "리플레이션",
)

_XML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_PKG_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def normalize_header(value: object) -> str:
    """Normalize headers for alias matching while preserving source columns."""
    return re.sub(r"[\s_\-:/()（）]+", "", str(value or "").strip().casefold())


def _column_index(reference: str) -> int:
    letters = re.match(r"[A-Z]+", reference.upper())
    if not letters:
        return 0
    index = 0
    for character in letters.group(0):
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for item in root.findall(f"{_XML_NS}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{_XML_NS}t")))
    return values


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    workbook = ElementTree.fromstring(archive.read("xl/workbook.xml"))
    first_sheet = workbook.find(f"{_XML_NS}sheets/{_XML_NS}sheet")
    if first_sheet is None:
        raise ValueError("workbook contains no worksheets")
    relationship_id = first_sheet.attrib.get(f"{_REL_NS}id")
    relationships = ElementTree.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for relationship in relationships.findall(f"{_PKG_REL_NS}Relationship"):
        if relationship.attrib.get("Id") == relationship_id:
            target = relationship.attrib["Target"].lstrip("/")
            return target if target.startswith("xl/") else f"xl/{target}"
    raise ValueError("first worksheet relationship is missing")


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    """Read the first worksheet as dictionaries without modifying the workbook."""
    if path.suffix.casefold() != ".xlsx":
        raise ValueError("only .xlsx is supported; .xls requires an approved reader")
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        sheet = ElementTree.fromstring(archive.read(_first_sheet_path(archive)))
    matrix: list[dict[int, str]] = []
    for row in sheet.findall(f".//{_XML_NS}row"):
        values: dict[int, str] = {}
        for cell in row.findall(f"{_XML_NS}c"):
            column = _column_index(cell.attrib.get("r", ""))
            cell_type = cell.attrib.get("t")
            if cell_type == "inlineStr":
                value = "".join(node.text or "" for node in cell.iter(f"{_XML_NS}t"))
            else:
                raw = cell.find(f"{_XML_NS}v")
                value = raw.text if raw is not None and raw.text is not None else ""
                if cell_type == "s" and value:
                    value = shared[int(value)]
            values[column] = value
        matrix.append(values)
    if not matrix:
        return []
    width = max((max(row, default=-1) for row in matrix), default=-1) + 1
    headers = [str(matrix[0].get(index, "")).strip() for index in range(width)]
    rows: list[dict[str, str]] = []
    for values in matrix[1:]:
        row = {
            headers[index]: str(values.get(index, "")).strip() for index in range(width)
        }
        if any(row.values()):
            rows.append(row)
    return rows


def discover_label_workbook(root: Path) -> list[Path]:
    """Find likely label workbooks while excluding virtual environments and git."""
    matches: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.parts[-2:-1] in ((".git",), (".venv",)):
            continue
        if path.name.casefold() in {name.casefold() for name in LABEL_CANDIDATE_NAMES}:
            matches.append(path)
    return sorted(matches)


def _first_column(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {normalize_header(header): header for header in headers}
    for alias in aliases:
        if normalize_header(alias) in normalized:
            return normalized[normalize_header(alias)]
    return None


def _text(value: object) -> str:
    text = "" if value is None else str(value)
    if text.casefold() in {"nan", "none", "null"}:
        return ""
    return text.strip()


def _number(value: object) -> float | None:
    text = _text(value).replace(",", "")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def analyze_label_rows(rows: list[dict[str, str]], source_path: Path) -> dict[str, Any]:
    """Run deterministic quality checks against dynamically discovered columns."""
    headers = list(rows[0]) if rows else []
    columns = {
        "id": _first_column(headers, ("원문ID", "문서ID", "document_id", "id")),
        "title": _first_column(headers, ("표제어", "용어", "term", "title")),
        "content": _first_column(
            headers, ("설명", "본문", "내용", "content", "definition")
        ),
        "source": _first_column(headers, ("출처", "자료출처", "source", "source_url")),
        "char_count": _first_column(headers, ("문자수", "글자수", "char_count")),
        "quality": _first_column(headers, ("원문품질", "자료품질", "품질")),
        "relevance": _first_column(headers, ("관련도", "relevance_score", "relevance")),
        "reviewer_a": _first_column(headers, ("평가자A", "평가자A라벨", "reviewer_a")),
        "reviewer_b": _first_column(headers, ("평가자B", "평가자B라벨", "reviewer_b")),
        "gold": _first_column(headers, ("확정골드", "골드라벨", "gold_label", "gold")),
        "reason": _first_column(headers, ("판정근거", "판정이유", "근거", "reason")),
        "quiz": _first_column(
            headers, ("문제생성적합", "문제생성용", "quiz_candidate")
        ),
        "tutor": _first_column(headers, ("튜터검색적합", "튜터용", "tutor_candidate")),
    }

    def values(key: str) -> list[str]:
        column = columns[key]
        return [_text(row.get(column, "")) for row in rows] if column else []

    ids = values("id")
    titles = values("title")
    contents = values("content")
    source_values = values("source")
    relevance_values = values("relevance")
    reviewer_a = values("reviewer_a")
    reviewer_b = values("reviewer_b")
    gold = values("gold")
    reasons = values("reason")
    disagreements = [
        {
            "row_number": index + 2,
            "document_id": ids[index] if ids else "",
            "reviewer_a": a,
            "reviewer_b": b,
        }
        for index, (a, b) in enumerate(zip(reviewer_a, reviewer_b))
        if a and b and a != b
    ]
    review_candidates: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        title = titles[index] if index < len(titles) else ""
        content = contents[index] if index < len(contents) else ""
        reasons_value = reasons[index] if index < len(reasons) else ""
        flags: list[str] = []
        if any(term in title or term in content for term in MANUAL_REVIEW_TERMS):
            flags.append("specified_manual_review_term")
        if not title:
            flags.append("empty_title")
        if not content:
            flags.append("empty_content")
        if not source_values or not source_values[index]:
            flags.append("missing_source")
        if (
            reasons_value
            and content
            and normalize_header(reasons_value) not in normalize_header(content)
        ):
            flags.append("reason_not_found_verbatim_in_content")
        if flags:
            review_candidates.append(
                {
                    "row_number": index + 2,
                    "document_id": ids[index] if ids else "",
                    "title": title,
                    "review_reason": ";".join(flags),
                    "current_relevance": relevance_values[index]
                    if index < len(relevance_values)
                    else "",
                    "content": content,
                }
            )

    invalid_relevance = [
        value for value in relevance_values if value and value not in {"0", "1", "2"}
    ]
    reason_counts = Counter(reason for reason in reasons if reason)
    repeated_reasons = {
        reason: count for reason, count in reason_counts.items() if count > 1
    }
    duplicate_ids = {
        value: count for value, count in Counter(ids).items() if value and count > 1
    }
    title_duplicates = {
        value: count for value, count in Counter(titles).items() if value and count > 1
    }
    content_duplicates = {
        value: count
        for value, count in Counter(contents).items()
        if value and count > 1
    }
    char_mismatches: list[int] = []
    if columns["char_count"]:
        for index, row in enumerate(rows):
            expected = _number(row.get(columns["char_count"], ""))
            if (
                expected is not None
                and index < len(contents)
                and int(expected) != len(contents[index])
            ):
                char_mismatches.append(index + 2)
    agreement = None
    if reviewer_a and reviewer_b:
        comparable = [(a, b) for a, b in zip(reviewer_a, reviewer_b) if a and b]
        agreement = {
            "comparable_count": len(comparable),
            "agree_count": sum(a == b for a, b in comparable),
            "disagree_count": sum(a != b for a, b in comparable),
            "agreement_rate": (
                sum(a == b for a, b in comparable) / len(comparable)
                if comparable
                else None
            ),
        }
    return {
        "status": "EXECUTED",
        "source_path": str(source_path),
        "row_count": len(rows),
        "headers": headers,
        "detected_columns": columns,
        "integrity": {
            "duplicate_ids": duplicate_ids,
            "duplicate_titles": title_duplicates,
            "duplicate_contents": content_duplicates,
            "empty_title_count": sum(not value for value in titles),
            "empty_content_count": sum(not value for value in contents),
            "missing_source_count": sum(not value for value in source_values),
            "char_count_mismatch_rows": char_mismatches,
            "invalid_relevance_values": invalid_relevance,
            "quality_flag_missing_count": sum(not value for value in values("quality")),
            "leading_or_trailing_whitespace_cells": sum(
                value != str(row.get(column, ""))
                for row in rows
                for column in headers
                for value in [_text(row.get(column, ""))]
                if row.get(column, "") not in (None, "")
            ),
            "replacement_character_count": sum(
                "�" in str(row.get(column, "")) for row in rows for column in headers
            ),
        },
        "label_consistency": {
            "reviewer_agreement": agreement,
            "disagreement_count": len(disagreements),
            "gold_vs_reviewer_a_mismatch_count": sum(
                a and g and a != g for a, g in zip(reviewer_a, gold)
            ),
            "gold_vs_reviewer_b_mismatch_count": sum(
                b and g and b != g for b, g in zip(reviewer_b, gold)
            ),
            "relevance_distribution": dict(Counter(relevance_values)),
            "quiz_values_present": bool(values("quiz")),
            "tutor_values_present": bool(values("tutor")),
        },
        "reason_audit": {
            "non_empty_reason_count": sum(bool(value) for value in reasons),
            "repeated_reasons": repeated_reasons,
            "reason_not_found_candidate_count": sum(
                "reason_not_found_verbatim_in_content" in row["review_reason"]
                for row in review_candidates
            ),
        },
        "manual_review_candidates": review_candidates,
        "disagreements": disagreements,
    }
