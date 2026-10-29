"""Read-only validation and candidate selection for the mentor dataset.

The mentor files are intentionally not bundled with the repository.  These
helpers validate them when a reviewer places the files under
``data/mentor_dataset``; they never download, repair, or approve data.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

EXPECTED_APPROVED_COUNT = 3514
EXPECTED_REVIEW_COUNT = 29
EXPECTED_SOURCE_COUNTS = {"BOK": 760, "KDI": 2754}
C0704_KEYWORDS = (
    "인플레이션",
    "디플레이션",
    "디스인플레이션",
    "물가상승",
    "물가하락",
    "물가상승률",
    "가격수준",
)
C0704_ALIASES = ("inflation", "deflation", "disinflation")


class MentorDatasetError(ValueError):
    """Raised for malformed input, never for a missing optional dataset."""


@dataclass(frozen=True, slots=True)
class DatasetReport:
    status: str
    approved_path: str
    review_path: str
    approved_count: int = 0
    review_count: int = 0
    source_counts: dict[str, int] | None = None
    review_source_counts: dict[str, int] | None = None
    duplicate_document_ids: tuple[str, ...] = ()
    duplicate_content_hashes: tuple[str, ...] = ()
    empty_content_document_ids: tuple[str, ...] = ()
    content_hash_mismatches: tuple[str, ...] = ()
    missing_fields: dict[str, tuple[str, ...]] | None = None
    licenses: dict[str, int] | None = None
    multi_source_terms: dict[str, tuple[str, ...]] | None = None
    expected_count_mismatches: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CurriculumReport:
    status: str
    path: str
    region_count: int = 0
    concept_count: int = 0
    normal_stage_count: int = 0
    boss_count: int = 0
    required_edge_count: int = 0
    recommended_edge_count: int = 0
    duplicate_concept_ids: tuple[str, ...] = ()
    duplicate_stage_ids: tuple[str, ...] = ()
    invalid_references: tuple[str, ...] = ()
    required_cycles: tuple[str, ...] = ()
    blueprint_missing_stage_ids: tuple[str, ...] = ()
    app_uuid_missing_concept_ids: tuple[str, ...] = ()
    draft_status: str | None = None
    unlock_policy_status: str | None = None
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise MentorDatasetError(
                f"invalid JSONL at {path}:{line_no}: {exc.msg}"
            ) from exc
        if not isinstance(row, dict):
            raise MentorDatasetError(f"JSONL row {line_no} must be an object")
        rows.append(row)
    return rows


def _source_type(row: dict[str, Any]) -> str:
    raw = " ".join(
        str(row.get(key, ""))
        for key in ("source_type", "publisher", "source_id", "source")
    ).casefold()
    if "kdi" in raw:
        return "KDI"
    if "bok" in raw or "한국은행" in raw:
        return "BOK"
    return str(row.get("source_type") or "UNKNOWN").upper()


def _duplicates(values: Iterable[str]) -> tuple[str, ...]:
    counts = Counter(value for value in values if value)
    return tuple(sorted(value for value, count in counts.items() if count > 1))


def inspect_terms_dataset(
    approved_path: Path,
    review_path: Path,
) -> DatasetReport:
    """Inspect both JSONL files without changing either file."""

    missing = [str(path) for path in (approved_path, review_path) if not path.is_file()]
    if missing:
        return DatasetReport(
            status="NOT_AVAILABLE",
            approved_path=str(approved_path),
            review_path=str(review_path),
            notes=(
                "Required mentor dataset file(s) are missing: " + ", ".join(missing),
            ),
        )

    approved = _read_jsonl(approved_path)
    review = _read_jsonl(review_path)
    all_rows = [*approved, *review]
    required = (
        "document_id",
        "source_id",
        "source_type",
        "title",
        "term",
        "definition",
        "content",
        "content_hash",
        "document_version",
        "source_url",
        "review_status",
        "license",
        "knowledge_scope",
    )
    missing_fields = {
        "approved": tuple(
            sorted(
                {
                    field
                    for field in required
                    if any(field not in row for row in approved)
                }
            )
        ),
        "needs_review": tuple(
            sorted(
                {field for field in required if any(field not in row for row in review)}
            )
        ),
    }
    document_ids = [str(row.get("document_id", "")) for row in all_rows]
    hashes = [str(row.get("content_hash", "")) for row in all_rows]
    empty = tuple(
        sorted(
            str(row.get("document_id", ""))
            for row in all_rows
            if not str(row.get("content", "")).strip()
        )
    )
    hash_mismatches = tuple(
        sorted(
            str(row.get("document_id", ""))
            for row in all_rows
            if row.get("content")
            and row.get("content_hash")
            != hashlib.sha256(str(row["content"]).encode("utf-8")).hexdigest()
        )
    )
    source_counts = dict(sorted(Counter(_source_type(row) for row in approved).items()))
    review_source_counts = dict(
        sorted(Counter(_source_type(row) for row in review).items())
    )
    licenses = dict(
        sorted(
            Counter(str(row.get("license") or "UNKNOWN") for row in all_rows).items()
        )
    )
    term_sources: defaultdict[str, set[str]] = defaultdict(set)
    for row in all_rows:
        term = str(row.get("term") or row.get("title") or "").strip()
        if term:
            term_sources[term].add(_source_type(row))
    multi_source_terms = {
        term: tuple(sorted(sources))
        for term, sources in term_sources.items()
        if len(sources) > 1
    }
    expected: list[str] = []
    if len(approved) != EXPECTED_APPROVED_COUNT:
        expected.append(
            f"terms_approved count={len(approved)} (expected {EXPECTED_APPROVED_COUNT})"
        )
    if len(review) != EXPECTED_REVIEW_COUNT:
        expected.append(
            f"terms_needs_review count={len(review)} (expected {EXPECTED_REVIEW_COUNT})"
        )
    for source, expected_count in EXPECTED_SOURCE_COUNTS.items():
        actual = source_counts.get(source, 0)
        if actual != expected_count:
            expected.append(f"{source} count={actual} (expected {expected_count})")

    notes: list[str] = [
        (
            "approved means preprocessing/indexing eligibility only; it is not "
            "expert, license, or pedagogical approval."
        ),
        "review_status and license values were read-only and were not changed.",
    ]
    invalid_review = [
        str(row.get("document_id", ""))
        for row in review
        if str(row.get("review_status", "")).casefold() == "approved"
    ]
    if invalid_review:
        notes.append(
            "needs_review contains approved rows: " + ", ".join(sorted(invalid_review))
        )
    status = (
        "VALID"
        if not (
            missing_fields["approved"]
            or missing_fields["needs_review"]
            or empty
            or hash_mismatches
            or _duplicates([str(row.get("document_id", "")) for row in approved])
        )
        else "INVALID"
    )
    if expected and status == "VALID":
        status = "VALID_WITH_EXPECTATION_MISMATCH"
    return DatasetReport(
        status=status,
        approved_path=str(approved_path),
        review_path=str(review_path),
        approved_count=len(approved),
        review_count=len(review),
        source_counts=source_counts,
        duplicate_document_ids=_duplicates(document_ids),
        duplicate_content_hashes=_duplicates(hashes),
        empty_content_document_ids=empty,
        content_hash_mismatches=hash_mismatches,
        missing_fields=missing_fields,
        licenses=licenses,
        review_source_counts=review_source_counts,
        multi_source_terms={
            key: value for key, value in sorted(multi_source_terms.items())
        },
        expected_count_mismatches=tuple(expected),
        notes=tuple(notes),
    )


def _flatten_stage_rows(regions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    stages: list[dict[str, Any]] = []
    for region in regions:
        for stage in region.get("stages") or region.get("stage_list") or []:
            if isinstance(stage, dict):
                stages.append(stage)
        boss = region.get("boss")
        if isinstance(boss, dict):
            stages.append({**boss, "stage_type": "BOSS"})
    return stages


def validate_curriculum(path: Path) -> CurriculumReport:
    if not path.is_file():
        return CurriculumReport(
            status="NOT_AVAILABLE",
            path=str(path),
            notes=(f"curriculum file is missing: {path}",),
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise MentorDatasetError("curriculum root must be an object")
    regions = [row for row in payload.get("regions", []) if isinstance(row, dict)]
    concepts = [row for row in payload.get("concepts", []) if isinstance(row, dict)]
    edges = [row for row in payload.get("edges", []) if isinstance(row, dict)]
    stages = _flatten_stage_rows(regions)
    concept_ids = [
        str(row.get("concept_id") or row.get("id") or "") for row in concepts
    ]
    stage_ids = [str(row.get("stage_id") or row.get("id") or "") for row in stages]
    known_concepts = set(filter(None, concept_ids))
    invalid_refs: set[str] = set()
    required_graph: defaultdict[str, set[str]] = defaultdict(set)
    required_count = recommended_count = 0
    for edge in edges:
        source = str(edge.get("source") or edge.get("from") or "")
        target = str(edge.get("target") or edge.get("to") or "")
        if source not in known_concepts or target not in known_concepts:
            invalid_refs.add(f"edge:{source}->{target}")
        # The production curriculum uses ``relation_type``.  Keep the
        # historical ``type``/``relation`` fallbacks for small fixtures and
        # older exports so validation remains backwards-compatible.
        kind = str(
            edge.get("relation_type") or edge.get("type") or edge.get("relation") or ""
        ).casefold()
        if kind == "required":
            required_count += 1
            required_graph[source].add(target)
        elif kind == "recommended":
            recommended_count += 1
    for concept in concepts:
        current = str(concept.get("concept_id") or concept.get("id") or "")
        for field in ("prerequisite_concept_ids", "recommended_prior_concept_ids"):
            for referenced in concept.get(field) or []:
                if str(referenced) not in known_concepts:
                    invalid_refs.add(f"{current}:{referenced}")
    cycles: set[str] = set()
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            try:
                cycles.update(stack[stack.index(node) :])
            except ValueError:
                cycles.add(node)
            return
        if node in visited:
            return
        visiting.add(node)
        for child in required_graph.get(node, set()):
            visit(child, [*stack, node])
        visiting.remove(node)
        visited.add(node)

    for node in known_concepts:
        visit(node, [])
    blueprint_missing = tuple(
        sorted(
            str(stage.get("stage_id") or stage.get("id") or "")
            for stage in stages
            if not stage.get("question_blueprint")
            or str(stage.get("authoring_status", "")).upper() == "NEEDS_AUTHORING"
        )
    )
    app_uuid_missing = tuple(
        sorted(
            str(row.get("concept_id") or row.get("id") or "")
            for row in concepts
            if not row.get("app_concept_id")
        )
    )
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    policy = payload.get("topic_unlock_policy")
    policy_status = policy.get("status") if isinstance(policy, dict) else None
    status = "VALID" if not (invalid_refs or cycles) else "INVALID"
    return CurriculumReport(
        status=status,
        path=str(path),
        region_count=len(regions),
        concept_count=len(concepts),
        normal_stage_count=sum(
            1 for stage in stages if str(stage.get("stage_type", "")).upper() != "BOSS"
        ),
        boss_count=sum(
            1 for stage in stages if str(stage.get("stage_type", "")).upper() == "BOSS"
        ),
        required_edge_count=required_count,
        recommended_edge_count=recommended_count,
        duplicate_concept_ids=_duplicates(concept_ids),
        duplicate_stage_ids=_duplicates(stage_ids),
        invalid_references=tuple(sorted(invalid_refs)),
        required_cycles=tuple(sorted(cycles)),
        blueprint_missing_stage_ids=blueprint_missing,
        app_uuid_missing_concept_ids=app_uuid_missing,
        draft_status=str(meta.get("status"))
        if meta.get("status") is not None
        else None,
        unlock_policy_status=str(policy_status) if policy_status is not None else None,
        notes=(
            (
                "required edges are treated as source-before-target prerequisites; "
                "recommended edges do not block progress."
            ),
            (
                "topic unlock policy is reported only and is never inferred from "
                "prerequisite edges."
            ),
        ),
    )


def _candidate_text(row: dict[str, Any]) -> str:
    values = [
        row.get("title"),
        row.get("term"),
        row.get("term_kr"),
        row.get("term_en"),
        row.get("definition"),
        row.get("content"),
        *(row.get("aliases") or []),
        *(row.get("english_aliases") or []),
    ]
    return " ".join(str(value or "") for value in values).casefold()


def select_c0704_candidates(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create unapproved C0704 candidate rows from existing records only."""
    output: list[dict[str, Any]] = []
    for row in rows:
        text = _candidate_text(row)
        matched = [
            keyword
            for keyword in (*C0704_KEYWORDS, *C0704_ALIASES)
            if keyword.casefold() in text
        ]
        if not matched:
            continue
        document_id = str(row.get("document_id") or "")
        term = str(row.get("term") or row.get("title") or "")
        ira_only = "인플레이션감축법" in term and not any(
            token in text
            for token in ("물가", "가격수준", "디플레이션", "디스인플레이션")
        )
        if ira_only:
            label = "EXCLUDE"
            reason = "인플레이션 키워드가 법률명(IRA)에 포함된 오탐 가능성"
            score = 0.05
        elif any(
            token in text for token in ("인플레이션", "디플레이션", "디스인플레이션")
        ):
            label = "DIRECT"
            score = min(0.95, 0.6 + 0.08 * len(set(matched)))
            reason = "개념 핵심 용어가 문서 제목·정의·본문에 직접 등장"
        else:
            label = "INDIRECT"
            score = min(0.7, 0.35 + 0.08 * len(set(matched)))
            reason = "물가·가격수준 관련 표현이 등장하지만 핵심 용어 직접 정의는 보류"
        output.append(
            {
                "concept_code": "C0704",
                "document_id": document_id,
                "chunk_id": row.get("chunk_id"),
                "source_id": row.get("source_id"),
                "source_type": _source_type(row),
                "term": term,
                "title": row.get("title") or term,
                "content_preview": str(row.get("content") or "")[:500],
                "relevance_score": round(score, 4),
                "classification_label": label,
                "classification_reason": reason
                + f"; matched={','.join(sorted(set(matched)))}",
                "subtopic": "inflation_deflation"
                if label == "DIRECT"
                else "price_level",
                "classifier_version": "keyword-v1",
                "review_status": "PENDING",
                "reviewer": None,
                "reviewed_at": None,
            }
        )
    return sorted(
        output, key=lambda item: (-item["relevance_score"], item["document_id"])
    )


def read_terms_for_candidates(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        raise FileNotFoundError(path)
    return _read_jsonl(path)
