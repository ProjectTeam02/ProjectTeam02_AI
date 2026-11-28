"""Human Gold review preparation kit (assignment, draft mapping, agreement, gaps).

이 모듈은 사람 검수를 *준비*만 합니다. 어떤 함수도 Gold 라벨, 승인 상태,
라이선스 승인 값을 만들거나 승격하지 않습니다.

- 배정 시트: 각 항목에 서로 다른 검수자 2명을 균형 있게 배정합니다.
- 매핑 초안: 기존 개념·출처 데이터에서 conceptCode·approvedEvidence *후보*만
  제안하며 상태는 항상 ``DRAFT``입니다.
- 일치도: append-only 검수 이력에서 검수자 쌍별 Cohen's kappa와 불일치 목록을
  계산합니다.
- 공백 점검: 개념·출처·선수관계·문서의 검수자/검수일/라이선스 공백을 나열합니다.
"""

from __future__ import annotations

import hashlib
from collections import Counter, defaultdict
from itertools import combinations
from typing import Any, Iterable, Mapping

DEFAULT_REVIEWERS = ("REVIEWER_A", "REVIEWER_B")
DRAFT_STATUS = "DRAFT"
APPROVED_VALUES = {"APPROVED", "INDEPENDENT_APPROVED"}

ASSIGNMENT_FIELDS = [
    "assignment_id",
    "dataset",
    "item_id",
    "source",
    "split",
    "title",
    "reviewer_1",
    "reviewer_2",
    "assignment_status",
    "review_tool",
]

GAP_FIELDS = [
    "asset_type",
    "asset_id",
    "title",
    "current_status",
    "missing_fields",
    "note",
]


def _text(value: object) -> str:
    value_text = "" if value is None else str(value).strip()
    return "" if value_text.casefold() in {"", "nan", "none", "null"} else value_text


def _stable_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# 1. 이중 검수 배정 시트
# ---------------------------------------------------------------------------


def build_assignment_rows(
    items: Iterable[Mapping[str, Any]],
    reviewers: Iterable[str] = DEFAULT_REVIEWERS,
) -> list[dict[str, str]]:
    """Assign two distinct reviewers per item, balanced across reviewer pairs.

    ``items`` must carry ``dataset`` and ``item_id``; ``source``, ``split``,
    ``title`` and ``review_tool`` are copied when present. Ordering is by a
    stable hash inside each dataset so KDI/BOK rows are interleaved and the
    same input always yields the same sheet.
    """
    reviewer_list = [_text(name) for name in reviewers]
    reviewer_list = [name for name in reviewer_list if name]
    if len(set(reviewer_list)) != len(reviewer_list):
        raise ValueError("reviewer names must be unique")
    if len(reviewer_list) < 2:
        raise ValueError("double review needs at least two reviewers")
    pairs = list(combinations(reviewer_list, 2))
    ordered = sorted(
        items,
        key=lambda item: (
            _text(item.get("dataset")),
            _stable_key(f"{_text(item.get('dataset'))}|{_text(item.get('item_id'))}"),
        ),
    )
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, str]] = []
    counters: Counter[str] = Counter()
    for item in ordered:
        dataset = _text(item.get("dataset"))
        item_id = _text(item.get("item_id"))
        if not dataset or not item_id:
            raise ValueError("every item needs dataset and item_id")
        if (dataset, item_id) in seen:
            raise ValueError(f"duplicate item: {dataset}/{item_id}")
        seen.add((dataset, item_id))
        first, second = pairs[counters[dataset] % len(pairs)]
        counters[dataset] += 1
        rows.append(
            {
                "assignment_id": f"{dataset}-{counters[dataset]:04d}",
                "dataset": dataset,
                "item_id": item_id,
                "source": _text(item.get("source")),
                "split": _text(item.get("split")),
                "title": _text(item.get("title")),
                "reviewer_1": first,
                "reviewer_2": second,
                # 배정 상태일 뿐 검수·승인 결과가 아닙니다.
                "assignment_status": "ASSIGNED_NOT_REVIEWED",
                "review_tool": _text(item.get("review_tool")),
            }
        )
    return rows


def reviewer_workload(rows: Iterable[Mapping[str, str]]) -> dict[str, dict[str, int]]:
    """Count assigned items per reviewer and dataset."""
    load: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        for key in ("reviewer_1", "reviewer_2"):
            load[row[key]][row["dataset"]] += 1
    return {name: dict(counts) for name, counts in sorted(load.items())}


# ---------------------------------------------------------------------------
# 2. conceptCode · approvedEvidence 매핑 초안 (DRAFT 고정)
# ---------------------------------------------------------------------------


def draft_concept_evidence_map(
    cases: Iterable[Mapping[str, Any]],
    concepts: Iterable[Mapping[str, Any]],
    concept_sources: Iterable[Mapping[str, str]] = (),
) -> list[dict[str, Any]]:
    """Propose conceptCode/evidence candidates without approving anything."""
    concept_list = list(concepts)
    by_document: dict[str, set[str]] = defaultdict(set)
    by_title: dict[str, set[str]] = defaultdict(set)
    for concept in concept_list:
        code = _text(concept.get("conceptCode"))
        if not code:
            continue
        by_title[_text(concept.get("title"))].add(code)
        for document_id in concept.get("sourceDocumentIds") or []:
            by_document[_text(document_id)].add(code)
    for row in concept_sources:
        code, document_id = (
            _text(row.get("concept_code")),
            _text(row.get("document_id")),
        )
        if code and document_id:
            by_document[document_id].add(code)

    drafts: list[dict[str, Any]] = []
    for case in cases:
        source_ids = [_text(value) for value in case.get("sourceIds") or []]
        candidates: dict[str, set[str]] = defaultdict(set)
        for source_id in source_ids:
            for code in by_document.get(source_id, ()):
                candidates[code].add("SOURCE_DOCUMENT_LINK")
        for title in case.get("expectedConcepts") or []:
            title = _text(title)
            for code in by_title.get(title, ()):
                candidates[code].add("TITLE_EXACT_MATCH")
            # 약한 후보: 제목 포함 관계. 사람이 반드시 확인해야 합니다.
            for concept_title, codes in by_title.items():
                if (
                    title
                    and concept_title
                    and concept_title != title
                    and (title in concept_title or concept_title in title)
                ):
                    for code in codes:
                        candidates[code].add("TITLE_PARTIAL_MATCH")
        evidence: list[dict[str, Any]] = []
        for item in case.get("evidenceCandidates") or []:
            blockers = []
            if _text(item.get("sourceReviewStatus")).upper() not in APPROVED_VALUES:
                blockers.append("SOURCE_REVIEW_NOT_APPROVED")
            if _text(item.get("licenseStatus")).upper() not in APPROVED_VALUES:
                blockers.append("LICENSE_NOT_APPROVED")
            if not _text(item.get("contentHash")):
                blockers.append("CONTENT_HASH_MISSING")
            evidence.append(
                {
                    "sourceId": _text(item.get("sourceId")),
                    "documentId": _text(item.get("documentId")),
                    "chunkId": _text(item.get("chunkId")),
                    "contentHash": _text(item.get("contentHash")),
                    "approvalBlockers": blockers,
                }
            )
        drafts.append(
            {
                "caseId": _text(case.get("caseId")),
                "sourceIds": source_ids,
                "expectedConcepts": list(case.get("expectedConcepts") or []),
                "conceptCodeCandidates": [
                    {"conceptCode": code, "matchedBy": sorted(reasons)}
                    for code, reasons in sorted(candidates.items())
                ],
                "evidenceCandidates": evidence,
                # 사람이 확정하기 전까지 항상 DRAFT. Gold 파일에 쓰지 않습니다.
                "mappingStatus": DRAFT_STATUS,
                "requiresHumanReview": True,
                "goldStatusUnchanged": _text(case.get("goldStatus")),
            }
        )
    return drafts


# ---------------------------------------------------------------------------
# 3. 이중 검수 일치도 (Cohen's kappa) 및 불일치 리포트
# ---------------------------------------------------------------------------


def cohen_kappa(labels_a: list[str], labels_b: list[str]) -> float | None:
    """Return Cohen's kappa, or ``None`` when it is undefined (pe == 1 / empty)."""
    if len(labels_a) != len(labels_b):
        raise ValueError("label lists must have the same length")
    total = len(labels_a)
    if total == 0:
        return None
    observed = sum(a == b for a, b in zip(labels_a, labels_b)) / total
    count_a, count_b = Counter(labels_a), Counter(labels_b)
    expected = sum(
        (count_a[label] / total) * (count_b[label] / total)
        for label in set(count_a) | set(count_b)
    )
    if expected >= 1.0:
        return None
    return (observed - expected) / (1.0 - expected)


def latest_labels(
    events: Iterable[Mapping[str, Any]], kind: str
) -> dict[str, dict[str, str]]:
    """Latest label per item and reviewer from an append-only history.

    ``kind="precision"`` reads ``gold_review`` events (document_id,
    reviewer_id, relevance_label); ``kind="tutor"`` reads ``tutor_review``
    CASE_REVIEW events (caseId, reviewerId, decision).
    """
    labels: dict[str, dict[str, str]] = defaultdict(dict)
    for event in events:
        if kind == "precision":
            if _text(event.get("review_status")) != "SINGLE_REVIEWED":
                continue
            item, reviewer = event.get("document_id"), event.get("reviewer_id")
            label = event.get("relevance_label")
        elif kind == "tutor":
            if event.get("eventType") != "CASE_REVIEW":
                continue
            item, reviewer = event.get("caseId"), event.get("reviewerId")
            label = event.get("decision")
        else:
            raise ValueError("kind must be precision or tutor")
        item, reviewer, label = _text(item), _text(reviewer), _text(label)
        if item and reviewer and label:
            labels[item][reviewer] = label
    return dict(labels)


def agreement_report(
    labels: Mapping[str, Mapping[str, str]],
    assigned_items: Iterable[str] = (),
) -> dict[str, Any]:
    """Pairwise kappa, disagreements, and items still waiting for a 2nd review."""
    pair_items: dict[tuple[str, str], list[str]] = defaultdict(list)
    disagreements: list[dict[str, Any]] = []
    single: list[str] = []
    for item, by_reviewer in sorted(labels.items()):
        reviewers = sorted(by_reviewer)
        if len(reviewers) < 2:
            single.append(item)
            continue
        for pair in combinations(reviewers, 2):
            pair_items[pair].append(item)
        if len({by_reviewer[name] for name in reviewers}) > 1:
            disagreements.append(
                {
                    "item_id": item,
                    "labels": {name: by_reviewer[name] for name in reviewers},
                    "adjudication_required": True,
                }
            )
    pairs = []
    for (first, second), items in sorted(pair_items.items()):
        a = [labels[item][first] for item in items]
        b = [labels[item][second] for item in items]
        kappa = cohen_kappa(a, b)
        pairs.append(
            {
                "reviewers": [first, second],
                "shared_items": len(items),
                "observed_agreement": round(
                    sum(x == y for x, y in zip(a, b)) / len(items), 4
                ),
                "cohen_kappa": None if kappa is None else round(kappa, 4),
            }
        )
    assigned = {_text(item) for item in assigned_items if _text(item)}
    return {
        "reviewed_item_count": len(labels),
        "double_reviewed_item_count": len(labels) - len(single),
        "awaiting_second_review": single,
        "not_started_count": len(assigned - set(labels)) if assigned else None,
        "pairs": pairs,
        "disagreement_count": len(disagreements),
        "disagreements": disagreements,
        "gold_is_not_auto_approved": True,
    }


# ---------------------------------------------------------------------------
# 4. 검수자 / 검수일 / 라이선스 공백 점검
# ---------------------------------------------------------------------------


def _gap(asset_type, asset_id, title, status, missing, note="") -> dict[str, str]:
    return {
        "asset_type": asset_type,
        "asset_id": asset_id,
        "title": title,
        "current_status": status,
        "missing_fields": ";".join(missing),
        "note": note,
    }


def curation_gaps(
    concepts: Iterable[Mapping[str, Any]],
    concept_sources: Iterable[Mapping[str, str]],
    prerequisites: Iterable[Mapping[str, str]],
    documents: Iterable[Mapping[str, str]],
    document_status: Mapping[str, Mapping[str, str]] | None = None,
) -> list[dict[str, str]]:
    """List assets whose reviewer, review date, or license record is empty.

    CSV 표시(``approve=Y``, ``decision=APPROVED``)는 DB 승인 이력이 아니므로
    검수자·검수일이 없으면 공백으로 집계합니다.
    """
    gaps: list[dict[str, str]] = []
    for concept in concepts:
        missing = [
            field
            for field in ("reviewedBy", "reviewedAt")
            if not _text(concept.get(field))
        ]
        if not concept.get("sourceDocumentIds"):
            missing.append("sourceDocumentIds")
        if missing:
            gaps.append(
                _gap(
                    "CONCEPT",
                    _text(concept.get("conceptCode")),
                    _text(concept.get("title")),
                    _text(concept.get("status")),
                    missing,
                )
            )
    for row in concept_sources:
        missing = [
            field
            for field in ("reviewed_by", "reviewed_at", "license_review_status")
            if not _text(row.get(field))
        ]
        if not _text(row.get("document_id")):
            missing.append("document_id")
        marked = _text(row.get("approve")).upper()
        note = (
            "CSV approve=Y 표시만 있음 (DB 승인 이력 아님)"
            if marked == "Y"
            else "승인 표시 없음"
        )
        gaps.append(
            _gap(
                "CONCEPT_SOURCE",
                f"{_text(row.get('concept_code'))}:"
                f"{_text(row.get('document_id')) or '-'}",
                _text(row.get("concept_title")),
                f"match={_text(row.get('match_type'))};approve={marked or '-'}",
                missing,
                note,
            )
        )
    for row in prerequisites:
        missing = [
            field
            for field in ("reviewed_by", "reviewed_at")
            if not _text(row.get(field))
        ]
        status = _text(row.get("current_status"))
        decision = _text(row.get("decision"))
        note = ""
        if decision and status != decision:
            note = f"CSV decision={decision}, DB 상태={status or '-'} (미반영)"
        if missing or note:
            gaps.append(
                _gap(
                    "PREREQUISITE",
                    f"{_text(row.get('concept_code'))}->"
                    f"{_text(row.get('prerequisite_concept_code'))}",
                    f"{_text(row.get('concept_title'))} <- "
                    f"{_text(row.get('prerequisite_title'))}",
                    status,
                    missing,
                    note,
                )
            )
    status_map = document_status or {}
    for row in documents:
        document_id = _text(row.get("document_id"))
        status = status_map.get(document_id, {})
        review = _text(status.get("source_review_status")).upper() or "UNKNOWN"
        license_status = _text(status.get("license_status")).upper() or "UNKNOWN"
        missing = ["reviewed_by", "reviewed_at"]
        if license_status not in APPROVED_VALUES:
            missing.append("license_review_status")
        gaps.append(
            _gap(
                "BOK_DOCUMENT",
                document_id,
                _text(row.get("title")),
                f"review={review};license={license_status}",
                missing,
                "" if status else "로컬 정규화 문서에서 상태를 찾지 못함",
            )
        )
    return gaps


def summarize_gaps(gaps: Iterable[Mapping[str, str]]) -> dict[str, dict[str, int]]:
    """Count gaps per asset type and missing field."""
    summary: dict[str, Counter[str]] = defaultdict(Counter)
    for gap in gaps:
        summary[gap["asset_type"]]["rows_with_gap"] += 1
        for field in filter(None, gap["missing_fields"].split(";")):
            summary[gap["asset_type"]][field] += 1
    return {asset: dict(counts) for asset, counts in sorted(summary.items())}
