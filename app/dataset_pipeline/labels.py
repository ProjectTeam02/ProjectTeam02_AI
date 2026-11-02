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
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

# 파일명이 팀 환경에 따라 다를 수 있으므로 한국어·영문 후보명을 함께 탐색합니다.
LABEL_CANDIDATE_NAMES = ("라벨링.xlsx", "labeling.xlsx", "labels.xlsx")
# 아래 용어는 자동으로 최종 라벨을 확정하지 않고 사람 검수 대상으로 남깁니다.
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
    # 공백·괄호·구분기호를 제거해 '평가자 A'와 '평가자A'를 같은 열로 인식합니다.
    normalized = unicodedata.normalize("NFKC", str(value or "").strip())
    return re.sub(r"[\s_\-:/()（）]+", "", normalized.casefold())


def normalize_filename(value: object) -> str:
    """Normalize filenames so macOS decomposed Korean names are discoverable."""
    # macOS에서 생성된 파일은 한글이 자모 단위로 저장될 수 있어 NFC로 통일합니다.
    return unicodedata.normalize("NFC", str(value or "")).casefold()


def _column_index(reference: str) -> int:
    # XLSX 셀 주소의 알파벳 부분을 0부터 시작하는 열 번호로 변환합니다.
    letters = re.match(r"[A-Z]+", reference.upper())
    if not letters:
        return 0
    index = 0
    for character in letters.group(0):
        index = index * 26 + ord(character) - ord("A") + 1
    return index - 1


def _shared_strings(archive: zipfile.ZipFile) -> list[str]:
    # 문자열을 sharedStrings.xml에 모아 저장하는 XLSX 파일을 지원합니다.
    try:
        root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for item in root.findall(f"{_XML_NS}si"):
        values.append("".join(node.text or "" for node in item.iter(f"{_XML_NS}t")))
    return values


def _first_sheet_path(archive: zipfile.ZipFile) -> str:
    # 라벨링 파일의 첫 번째 시트를 읽기 위한 실제 XML 경로를 찾습니다.
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
    # 별도 Excel 편집 라이브러리 없이 표준 ZIP/XML 모듈만 사용합니다.
    if path.suffix.casefold() != ".xlsx":
        raise ValueError("only .xlsx is supported; .xls requires an approved reader")
    with zipfile.ZipFile(path) as archive:
        shared = _shared_strings(archive)
        sheet = ElementTree.fromstring(archive.read(_first_sheet_path(archive)))
    # 첫 행은 헤더, 나머지 행은 헤더와 연결할 셀 값으로 임시 보관합니다.
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
    # 가상환경과 Git 내부 파일은 실제 라벨 데이터가 아니므로 후보에서 제외합니다.
    matches: list[Path] = []
    candidate_names = {normalize_filename(name) for name in LABEL_CANDIDATE_NAMES}
    for path in root.rglob("*"):
        if not path.is_file() or path.parts[-2:-1] in ((".git",), (".venv",)):
            continue
        normalized_name = normalize_filename(path.name)
        # 정확한 후보명뿐 아니라 '라벨'이 포함된 xlsx도 허용합니다.
        # 그 외 엑셀 파일은 라벨 원본으로 추정하지 않습니다.
        is_label_name = normalized_name in candidate_names or (
            path.suffix.casefold() == ".xlsx"
            and ("라벨" in normalized_name or "label" in normalized_name)
        )
        if is_label_name:
            matches.append(path)
    return sorted(matches)


def _first_column(headers: list[str], aliases: tuple[str, ...]) -> str | None:
    # 실제 열 이름이 달라도 미리 정의한 한국어·영문 별칭으로 연결합니다.
    normalized = {normalize_header(header): header for header in headers}
    for alias in aliases:
        if normalize_header(alias) in normalized:
            return normalized[normalize_header(alias)]
    return None


def _text(value: object) -> str:
    # 엑셀의 빈 셀·문자열형 결측치를 동일하게 빈 문자열로 통일합니다.
    text = "" if value is None else str(value)
    if text.casefold() in {"nan", "none", "null"}:
        return ""
    return text.strip()


def _number(value: object) -> float | None:
    # 문자 수 열처럼 숫자여야 하는 값만 변환하고, 이상값은 결측으로 남깁니다.
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
    # 실제 열을 감지하고, 없는 열은 임의로 만들지 않고 검사 불가로 남깁니다.
    headers = list(rows[0]) if rows else []
    columns = {
        "id": _first_column(headers, ("원문ID", "문서ID", "document_id", "id")),
        "title": _first_column(headers, ("표제어", "용어", "term", "title")),
        "content": _first_column(
            headers, ("설명", "본문", "내용", "content", "definition")
        ),
        "source": _first_column(headers, ("출처", "자료출처", "source", "source_url")),
        "source_locator": _first_column(
            headers, ("원문 위치", "원문위치", "source_locator", "source_url", "url")
        ),
        "char_count": _first_column(headers, ("문자수", "글자수", "char_count")),
        "quality_flag": _first_column(
            headers, ("원본 점검플래그", "원본점검플래그", "quality_flag")
        ),
        "quality": _first_column(headers, ("원문품질", "자료품질", "품질")),
        # 확정 골드는 관련도 A/B와 별도인 독립 라벨 열입니다.
        "relevance": _first_column(
            headers, ("확정 골드", "확정골드", "관련도", "relevance_score", "relevance")
        ),
        "reviewer_a": _first_column(
            headers, ("관련도 A", "관련도A", "평가자A", "평가자A라벨", "reviewer_a")
        ),
        "reviewer_b": _first_column(
            headers, ("관련도 B", "관련도B", "평가자B", "평가자B라벨", "reviewer_b")
        ),
        "gold": _first_column(headers, ("확정골드", "골드라벨", "gold_label", "gold")),
        "reason": _first_column(headers, ("판정근거", "판정이유", "근거", "reason")),
        "quiz": _first_column(
            headers, ("문제생성적합", "문제생성용", "quiz_candidate")
        ),
        "tutor": _first_column(headers, ("튜터검색적합", "튜터용", "tutor_candidate")),
        "keyword": _first_column(headers, ("키워드 분류", "키워드분류", "keyword")),
        "binary_label": _first_column(
            headers, ("평가용 이진 라벨", "평가용이진라벨", "binary_label")
        ),
        "b_review": _first_column(
            headers, ("B 재검토 대상", "B재검토대상", "reviewer_b_review")
        ),
    }

    # 실제 파일에서 '확정 골드' 표기가 공백 포함 형태인지에 관계없이 감지합니다.
    if columns["gold"] is None:
        columns["gold"] = _first_column(
            headers, ("확정 골드", "확정골드", "gold_label", "gold")
        )

    def values(key: str) -> list[str]:
        # 열이 없으면 빈 목록을 반환해 '미입력'과 '검사 대상 없음'을 구분합니다.
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
    source_locators = values("source_locator")
    quality_flags = values("quality_flag")
    quality_values = values("quality")
    reviewer_a_scores = [_number(value) for value in reviewer_a]
    reviewer_b_scores = [_number(value) for value in reviewer_b]
    gold_scores = [_number(value) for value in values("gold")]

    def meaningful_tokens(value: str) -> set[str]:
        # 조사와 문장 부호를 제외한 2글자 이상 토큰으로
        # 근거 겹침을 보수적으로 확인합니다.
        stopwords = {
            "해당",
            "설명",
            "관련",
            "판정",
            "정도",
            "단원",
            "학습",
            "내용",
            "대해",
            "있어",
            "으로",
        }
        return {
            token
            for token in re.findall(
                r"[가-힣A-Za-z][가-힣A-Za-z0-9]{1,}", value.casefold()
            )
            if token not in stopwords
        }

    # 두 평가자가 모두 입력한 행만 비교하여 빈 칸을 불일치로 세지 않습니다.
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
        # 한 행의 검수 사유를 누적해 사람이 우선순위를 정할 수 있게 합니다.
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
        if not source_locators or not source_locators[index]:
            flags.append("missing_source_locator")
        if quality_flags and quality_flags[index]:
            flags.append("original_quality_flag_present")
        if quality_values and quality_values[index] and quality_values[index] != "정상":
            flags.append("non_normal_quality")
        # 판정 근거가 본문을 그대로 복사했는지는 요구하지 않습니다.
        # 의미 토큰이 전혀 겹치면 사람 검토 신호로 남깁니다.
        if (
            reasons_value
            and content
            and not (meaningful_tokens(reasons_value) & meaningful_tokens(content))
        ):
            flags.append("reason_has_no_content_token_overlap")
        if index < len(reviewer_a_scores) and index < len(reviewer_b_scores):
            if (
                reviewer_a_scores[index] is not None
                and reviewer_b_scores[index] is not None
            ):
                if reviewer_a_scores[index] != reviewer_b_scores[index]:
                    flags.append("reviewer_disagreement")
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

    # 정의된 0·1·2 범위를 벗어난 값은 입력 오류 후보로 분리합니다.
    invalid_relevance = [
        value for value in values("gold") if value and value not in {"0", "1", "2"}
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
    # 문자 수 열이 실제로 존재할 때만 본문 길이와 비교합니다.
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
    # 평가자 A와 B 열이 모두 있을 때만 일치율을 계산합니다.
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
    # 결과는 원본 행을 수정하지 않고, 보고서 생성에 필요한 검사 결과만 반환합니다.
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
            "missing_source_locator_count": sum(not value for value in source_locators),
            "char_count_mismatch_rows": char_mismatches,
            "invalid_relevance_values": invalid_relevance,
            "quality_flag_missing_count": sum(not value for value in quality_values),
            "original_quality_flag_count": sum(bool(value) for value in quality_flags),
            "quality_distribution": dict(
                Counter(value for value in quality_values if value)
            ),
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
                bool(a and g and a != g) for a, g in zip(reviewer_a, gold)
            ),
            "gold_vs_reviewer_b_mismatch_count": sum(
                bool(b and g and b != g) for b, g in zip(reviewer_b, gold)
            ),
            "reviewer_a_distribution": dict(
                Counter(value for value in reviewer_a if value)
            ),
            "reviewer_b_distribution": dict(
                Counter(value for value in reviewer_b if value)
            ),
            "relevance_distribution": dict(
                Counter(value for value in values("gold") if value)
            ),
            "reviewer_a_filled_count": sum(bool(value) for value in reviewer_a),
            "reviewer_b_filled_count": sum(bool(value) for value in reviewer_b),
            "gold_filled_count": sum(bool(value) for value in values("gold")),
            "quiz_values_present": bool(values("quiz")),
            "tutor_values_present": bool(values("tutor")),
            "quiz_policy_mismatch_count": sum(
                bool(value)
                and gold_scores[index] is not None
                and ((value == "적합") != (gold_scores[index] == 2))
                for index, value in enumerate(values("quiz"))
                if index < len(gold_scores)
            ),
            "tutor_policy_mismatch_count": sum(
                bool(value)
                and gold_scores[index] is not None
                and ((value == "적합") != (gold_scores[index] in {1, 2}))
                for index, value in enumerate(values("tutor"))
                if index < len(gold_scores)
            ),
        },
        "reason_audit": {
            "non_empty_reason_count": sum(bool(value) for value in reasons),
            "repeated_reasons": repeated_reasons,
            "reason_without_content_overlap_count": sum(
                "reason_has_no_content_token_overlap" in row["review_reason"]
                for row in review_candidates
            ),
        },
        "manual_review_candidates": review_candidates,
        "disagreements": disagreements,
    }
