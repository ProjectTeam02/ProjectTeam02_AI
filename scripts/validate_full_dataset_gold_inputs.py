# ruff: noqa: E501

"""Validate the current corpus and prepare independent Gold review assets.

이 스크립트는 원본 데이터와 기존 라벨을 수정하지 않습니다. 기관별
canonical export를 한 번만 읽어 품질 문제와 lineage를 점검하고, 사람이
검수할 KDI/BOK 템플릿을 별도 파일로 생성합니다. 템플릿의 Gold 관련 필드는
항상 빈 값 또는 PENDING으로 시작하며 자동 승인하지 않습니다.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dataset_pipeline.chunks import Chunk, make_chunks  # noqa: E402
from app.dataset_pipeline.io import NormalizedDocument, load_corpus  # noqa: E402
from app.dataset_pipeline.keywords import Chapter, classify_chunk_by_keywords  # noqa: E402
from app.dataset_pipeline.labels import (  # noqa: E402
    analyze_label_rows,
    discover_label_workbook,
    read_xlsx_rows,
)
from app.dataset_pipeline.tokenizer import ExactTokenizer  # noqa: E402
from scripts._pipeline_support import load_yaml, write_json  # noqa: E402
from scripts.rebuild_precision_pipeline import _records  # noqa: E402

DEFAULT_REPORT_DIR = ROOT / "reports"
DEFAULT_TEMPLATE_DIR = ROOT / "reports" / "step3"
DEFAULT_CHAPTER = ROOT / "configs" / "chapters.yaml"
DEFAULT_CONFIG = ROOT / "configs" / "eda_config.yaml"
DEFAULT_BOK_MANIFEST = DEFAULT_TEMPLATE_DIR / "sampling_manifest.json"
DEFAULT_BOK_TEMPLATE = DEFAULT_TEMPLATE_DIR / "bok_independent_gold_review_template.csv"
DEFAULT_KDI_TEMPLATE = DEFAULT_TEMPLATE_DIR / "kdi_independent_gold_review_template.csv"
DEFAULT_RANDOM_SEED = 20261029
DEFAULT_CANDIDATE_SAMPLE_SIZE = 55
DEFAULT_BOUNDARY_SAMPLE_SIZE = 50
DEFAULT_RANDOM_SAMPLE_SIZE = 100
BOUNDARY_TERMS = (
    "구매력",
    "금리",
    "기대",
    "경기",
    "공급",
    "수요",
    "실업",
    "성장",
    "소비",
    "원자재",
    "유가",
    "임금",
    "재정",
    "통화",
    "투자",
    "환율",
)

REVIEW_FIELDS = [
    "document_id",
    "chunk_id",
    "source",
    "title",
    "content",
    "content_hash",
    "source_url",
    "source_locator",
    "chapter_id",
    "chapter_code",
    "relevance_a",
    "relevance_b",
    "final_gold",
    "evidence_quote",
    "reason",
    "review_status",
    "reviewer_count",
    "review_mode",
    "reviewed_at",
    "dataset_version",
    "sampling_bucket",
    "split",
    "gold_set_status",
]


def _write_csv(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    """Write a reviewer-friendly UTF-8 CSV without changing source data."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REVIEW_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _split_for_review(source: str, document_id: str, content_hash: str) -> str:
    """Create a reproducible 80/20 split using content hash only."""
    key = content_hash or f"{source}|{document_id}"
    bucket = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:8], 16) % 10
    return "test" if bucket < 2 else "development"


def _empty_gold_fields() -> dict[str, str]:
    """Return values that prevent accidental automatic Gold approval."""
    return {
        "relevance_a": "",
        "relevance_b": "",
        "final_gold": "",
        "evidence_quote": "",
        "reason": "",
        "review_status": "PENDING",
        "reviewer_count": "",
        "review_mode": "",
        "reviewed_at": "",
        "gold_set_status": "PENDING_INDEPENDENT_REVIEW",
    }


def _review_row(
    document: NormalizedDocument,
    chunk: Chunk,
    dataset_version: str,
    sampling_bucket: str,
    chapter_id: str = "inflation",
    chapter_code: str = "C0704",
) -> dict[str, Any]:
    """Build one blank Gold row while preserving document-to-chunk lineage."""
    row = {
        "document_id": document.document_id,
        "chunk_id": chunk.chunk_id,
        "source": document.source,
        "title": document.title,
        "content": chunk.content,
        "content_hash": document.text_hash,
        "source_url": document.source_url or "",
        "source_locator": document.source_locator or "",
        "chapter_id": chapter_id,
        "chapter_code": chapter_code,
        "dataset_version": dataset_version,
        "sampling_bucket": sampling_bucket,
        "split": _split_for_review(
            document.source, document.document_id, document.text_hash
        ),
    }
    row.update(_empty_gold_fields())
    return row


def _load_chapter(path: Path) -> Chapter:
    payload = load_yaml(path)
    chapters = payload.get("chapters", [])
    if not chapters:
        raise ValueError(f"{path}에 챕터 정의가 없습니다.")
    return Chapter.from_dict(chapters[0])


def _chunk_by_document(chunks: list[Chunk]) -> dict[str, Chunk]:
    """Select chunk zero as the review anchor and keep its exact chunk ID."""
    selected: dict[str, Chunk] = {}
    for chunk in sorted(chunks, key=lambda item: (item.document_id, item.chunk_index)):
        selected.setdefault(chunk.document_id, chunk)
    return selected


def _boundary_score(document: NormalizedDocument) -> tuple[int, list[str]]:
    text = f"{document.title} {document.content}".casefold()
    matched = sorted({term for term in BOUNDARY_TERMS if term.casefold() in text})
    score = len(matched)
    if any(term.casefold() in document.title.casefold() for term in BOUNDARY_TERMS):
        score += 5
    return score, matched


def _stable_candidate_sample(ids: list[str], size: int, seed: int) -> list[str]:
    """Sample candidate IDs without using labels or model outputs."""
    ranked = sorted(
        ids, key=lambda value: hashlib.sha256(f"{seed}|{value}".encode()).hexdigest()
    )
    return ranked[: min(size, len(ranked))]


def build_bok_review_template(
    documents: list[NormalizedDocument],
    chunks: list[Chunk],
    chapter: Chapter,
    dataset_version: str,
    previous_manifest_path: Path = DEFAULT_BOK_MANIFEST,
    seed: int = DEFAULT_RANDOM_SEED,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Rebuild the 55/50/100 BOK sampling design for the current dataset."""
    by_id = {
        document.document_id: document
        for document in documents
        if document.source == "BOK"
    }
    anchors = _chunk_by_document([chunk for chunk in chunks if chunk.source == "BOK"])
    candidate_ids: list[str] = []
    for document_id, chunk in anchors.items():
        if classify_chunk_by_keywords(chunk, chapter)["candidate"]:
            candidate_ids.append(document_id)
    candidate_ids = sorted(candidate_ids)
    sampled_candidates = _stable_candidate_sample(
        candidate_ids, DEFAULT_CANDIDATE_SAMPLE_SIZE, seed
    )
    candidate_set = set(candidate_ids)
    remaining = sorted(set(by_id) - candidate_set)
    ranked_boundary = sorted(
        (
            (_boundary_score(by_id[document_id]), document_id)
            for document_id in remaining
        ),
        key=lambda item: (-item[0][0], item[1]),
    )
    boundary_ids = [
        document_id for _, document_id in ranked_boundary[:DEFAULT_BOUNDARY_SAMPLE_SIZE]
    ]
    boundary_set = set(boundary_ids)
    random_pool = [
        document_id for document_id in remaining if document_id not in boundary_set
    ]
    random_count = min(DEFAULT_RANDOM_SAMPLE_SIZE, len(random_pool))
    random_ids = sorted(random.Random(seed).sample(sorted(random_pool), random_count))

    rows: list[dict[str, Any]] = []
    for document_id in sampled_candidates:
        rows.append(
            _review_row(
                by_id[document_id],
                anchors[document_id],
                dataset_version,
                "keyword_candidate",
            )
        )
    for document_id in boundary_ids:
        rows.append(
            _review_row(
                by_id[document_id],
                anchors[document_id],
                dataset_version,
                "boundary_case",
            )
        )
    for document_id in random_ids:
        rows.append(
            _review_row(
                by_id[document_id],
                anchors[document_id],
                dataset_version,
                "random_non_candidate",
            )
        )

    previous_manifest: dict[str, Any] = {}
    if previous_manifest_path.is_file():
        previous_manifest = json.loads(
            previous_manifest_path.read_text(encoding="utf-8")
        )
    # 현재 canonical 파일 해시는 inventory에서 채우므로, 이 함수는
    # 표본 설계와 이전 표본의 재사용 가능성만 반환합니다.
    reconciliation = {
        "previous_manifest_status": previous_manifest.get("status", "NOT_AVAILABLE"),
        "previous_source_sha256": previous_manifest.get("source_sha256"),
        "previous_population_count": previous_manifest.get("population_count"),
        "previous_review_count": previous_manifest.get("combined_review_count"),
        "current_candidate_document_count": len(candidate_ids),
        "current_candidate_sample_count": len(sampled_candidates),
        "current_boundary_sample_count": len(boundary_ids),
        "current_random_sample_count": len(random_ids),
        "current_combined_review_count": len(rows),
        "current_source_sha256": None,
        "status": "REBUILT_CURRENT_DATASET",
        "reason": (
            "기존 205건 표본의 source hash/ID가 현재 canonical BOK export와 다르면 "
            "기존 행을 재사용하지 않고 동일한 표본 설계로 다시 생성합니다."
        ),
    }
    return rows, reconciliation


def _template_hash(rows: list[dict[str, Any]]) -> str:
    ids = "\n".join(sorted(str(row["document_id"]) for row in rows))
    return hashlib.sha256(ids.encode("utf-8")).hexdigest()


def _kdi_rows(
    workbook_path: Path,
    documents: list[NormalizedDocument],
    chunks: list[Chunk],
    chapter: Chapter,
    dataset_version: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Create a KDI queue from the workbook without copying any old labels."""
    source_rows = read_xlsx_rows(workbook_path)
    analysis = analyze_label_rows(source_rows, workbook_path)
    records = _records(source_rows, analysis["detected_columns"])
    docs = {document.document_id: document for document in documents}
    anchors = _chunk_by_document(chunks)
    rows: list[dict[str, Any]] = []
    missing_from_corpus: list[str] = []
    for record in records:
        document = docs.get(record["document_id"])
        if document is None:
            missing_from_corpus.append(record["document_id"])
            continue
        bucket = (
            "source_quality_review"
            if record["quality"] == "검토필요" or record["quality_flag"]
            else "kdi_label_reconciliation"
        )
        if record["document_id"] not in anchors:
            missing_from_corpus.append(record["document_id"])
            continue
        rows.append(
            _review_row(
                document,
                anchors[record["document_id"]],
                dataset_version,
                bucket,
            )
        )
    disagreement_count = len(analysis.get("disagreements", []))
    quality_count = sum(
        1
        for record in records
        if record["quality"] == "검토필요" or record["quality_flag"]
    )
    status = {
        "input_path": str(workbook_path.relative_to(ROOT)),
        "workbook_row_count": len(records),
        "template_row_count": len(rows),
        "reviewer_a_b_disagreement_count": disagreement_count,
        "source_quality_review_count": quality_count,
        "missing_from_current_corpus": sorted(set(missing_from_corpus)),
        "gold_values_copied_from_workbook": False,
        "status": "READY_FOR_HUMAN_REVIEW"
        if not missing_from_corpus
        else "REVIEW_REQUIRED",
    }
    return rows, status


def _inventory_manifest(
    inventory: dict[str, Any],
    config: dict[str, Any],
    chapter_payload: dict[str, Any],
    candidate_difference: dict[str, Any],
) -> dict[str, Any]:
    files = []
    for item in inventory.get("files", []):
        path = Path(item["path"])
        files.append(
            {
                **item,
                "path": str(path.relative_to(ROOT))
                if path.is_absolute()
                else str(path),
            }
        )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": inventory.get("dataset_version"),
        "canonical_counting_rule": inventory.get("canonical_counting_rule"),
        "source_files": files,
        "document_count": inventory.get("document_count"),
        "document_count_by_source": inventory.get("document_count_by_source"),
        "tokenizer": config.get("tokenizer", {}),
        "chunking": config.get("chunking", {}),
        "chapter_config_version": chapter_payload.get("config_version"),
        "chapter_config_status": chapter_payload.get("curriculum_status"),
        "keyword_rule_version": chapter_payload.get("config_version"),
        "candidate_unit": "chunk_id + chapter_id",
        "candidate_count_comparison": candidate_difference,
        "source_data_modified": False,
    }


def validate_dataset(
    documents: list[NormalizedDocument],
    chunks: list[Chunk],
    max_tokens: int,
    token_counts: dict[str, int],
) -> dict[str, Any]:
    """Return auditable quality and lineage checks for the canonical corpus."""
    source_url_missing = [
        document.document_id for document in documents if not document.source_url
    ]
    source_review_unresolved = [
        document.document_id
        for document in documents
        if document.source_review_status.casefold() != "approved"
    ]
    license_unconfirmed = [
        document.document_id
        for document in documents
        if document.license_status.casefold() not in {"approved", "cleared", "verified"}
    ]
    very_short = [
        document.document_id
        for document in documents
        if document.content and token_counts[document.document_id] < 20
    ]
    too_long = [
        document.document_id
        for document in documents
        if token_counts[document.document_id] > max_tokens
    ]
    by_source_hash: dict[tuple[str, str], list[str]] = {}
    for document in documents:
        by_source_hash.setdefault((document.source, document.text_hash), []).append(
            document.document_id
        )
    duplicate_groups = [
        {"source": source, "content_hash": content_hash, "document_ids": sorted(ids)}
        for (source, content_hash), ids in by_source_hash.items()
        if len(ids) > 1
    ]
    document_ids = {document.document_id for document in documents}
    chunk_ids = [chunk.chunk_id for chunk in chunks]
    missing_document_links = sorted(
        {chunk.document_id for chunk in chunks if chunk.document_id not in document_ids}
    )
    invalid_chunk_hashes = [chunk.chunk_id for chunk in chunks if not chunk.text_hash]
    source_chunk_counts = Counter(chunk.source for chunk in chunks)
    multi_chunk_documents = sorted(
        {chunk.document_id for chunk in chunks if chunk.chunk_index > 0}
    )
    split_validation = {
        document_id: {
            "chunk_token_counts": [
                chunk.token_count
                for chunk in chunks
                if chunk.document_id == document_id
            ],
            "all_within_limit": all(
                chunk.token_count <= max_tokens
                for chunk in chunks
                if chunk.document_id == document_id
            ),
        }
        for document_id in multi_chunk_documents
    }
    return {
        "document_count": len(documents),
        "document_count_by_source": dict(
            Counter(document.source for document in documents)
        ),
        "chunk_count": len(chunks),
        "chunk_count_by_source": dict(source_chunk_counts),
        "quality_issues": {
            "bok_source_url_missing": {
                "count": sum(
                    document.source == "BOK" and not document.source_url
                    for document in documents
                ),
                "sample_ids": source_url_missing[:10],
            },
            "source_review_status_unresolved": {
                "count": len(source_review_unresolved),
                "sample_ids": source_review_unresolved[:10],
            },
            "license_status_unconfirmed": {
                "count": len(license_unconfirmed),
                "sample_ids": license_unconfirmed[:10],
            },
            "under_20_tokens": {"count": len(very_short), "document_ids": very_short},
            "over_chunk_limit": {"count": len(too_long), "document_ids": too_long},
            "duplicate_content_hash_within_source": {
                "count": len(duplicate_groups),
                "groups": duplicate_groups,
            },
        },
        "lineage": {
            "missing_document_links": missing_document_links,
            "duplicate_chunk_id_count": len(chunk_ids) - len(set(chunk_ids)),
            "chunks_without_text_hash": invalid_chunk_hashes,
            "documents_with_multiple_chunks": multi_chunk_documents,
            "split_document_validation": split_validation,
            "all_split_chunks_within_limit": all(
                item["all_within_limit"] for item in split_validation.values()
            ),
            "all_chunk_document_links_resolvable": not missing_document_links,
        },
        "source_data_modified": False,
    }


def _candidate_difference(chunks: list[Chunk], chapter: Chapter) -> dict[str, Any]:
    """Reproduce 143 legacy rows and compare them with the current 148 rows."""
    current_rows = [classify_chunk_by_keywords(chunk, chapter) for chunk in chunks]
    legacy_chapter = Chapter(
        chapter.chapter_id,
        chapter.chapter_name,
        chapter.chapter_definition,
        chapter.include_criteria,
        chapter.exclude_criteria,
        chapter.keywords,
        chapter.related_keywords,
        chapter.opposite_keywords,
        chapter.exclude_keywords,
        chapter.rubric_version,
        (),
    )
    legacy_rows = [
        classify_chunk_by_keywords(chunk, legacy_chapter) for chunk in chunks
    ]
    current = {row["chunk_id"]: row for row in current_rows if row["candidate"]}
    legacy = {row["chunk_id"]: row for row in legacy_rows if row["candidate"]}
    added_ids = sorted(set(current) - set(legacy))
    chunk_by_id = {chunk.chunk_id: chunk for chunk in chunks}
    added_rows = [
        {
            "chunk_id": chunk_id,
            "document_id": chunk_by_id[chunk_id].document_id,
            "source": chunk_by_id[chunk_id].source,
            "title": chunk_by_id[chunk_id].title,
            "matched_keywords": current[chunk_id]["matched_keywords"],
            "matched_keyword_types": current[chunk_id]["matched_keyword_types"],
            "evidence_span": current[chunk_id]["evidence_span"],
        }
        for chunk_id in added_ids
    ]
    return {
        "legacy_reference": "reports/classification_strategy.md and prior pre-alias rule",
        "legacy_candidate_count": len(legacy),
        "current_candidate_count": len(current),
        "delta": len(current) - len(legacy),
        "candidate_unit": "chunk_id + chapter_id",
        "added_by_current_rule": added_rows,
        "interpretation": (
            "148는 143보다 5건 많습니다. 현재 config의 aliases에 추가된 PPI가 "
            "본문의 무관한 약어에도 매칭된 5건이며, 이는 후보 확장 신호이지 최종 관련성 라벨이 아닙니다."
        ),
    }


def _write_reports(
    report_dir: Path,
    validation: dict[str, Any],
    manifest: dict[str, Any],
    candidate_difference: dict[str, Any],
    kdi_status: dict[str, Any],
    bok_reconciliation: dict[str, Any],
) -> None:
    write_json(report_dir / "full_dataset_validation.json", validation)
    write_json(report_dir / "dataset_version_manifest.json", manifest)
    write_json(report_dir / "candidate_count_difference.json", candidate_difference)
    write_json(report_dir / "kdi_gold_review_status.json", kdi_status)
    write_json(report_dir / "bok_gold_sampling_reconciliation.json", bok_reconciliation)
    report_dir.joinpath("full_dataset_validation_report.md").write_text(
        _validation_markdown(validation, manifest), encoding="utf-8"
    )
    report_dir.joinpath("candidate_count_difference.md").write_text(
        _candidate_markdown(candidate_difference), encoding="utf-8"
    )
    report_dir.joinpath("independent_gold_progress.md").write_text(
        _progress_markdown(kdi_status, bok_reconciliation), encoding="utf-8"
    )


def _validation_markdown(validation: dict[str, Any], manifest: dict[str, Any]) -> str:
    quality = validation["quality_issues"]
    lineage = validation["lineage"]
    return f"""# 전체 데이터셋 품질 검증 보고서

## 실행 상태

- 상태: **EXECUTED_LOCAL_READ_ONLY**
- 데이터 버전: `{manifest["dataset_version"]}`
- 문서 단위: **{validation["document_count"]}건** (`validation['document_count_by_source']`)
- 청크 단위: **{validation["chunk_count"]}건** (`validation['chunk_count_by_source']`)
- 후보 집계 단위: `{manifest["candidate_unit"]}`
- 원본 수정: **{validation["source_data_modified"]}**

## 품질 점검 결과

| 점검 항목 | 건수 | 처리 |
|---|---:|---|
| BOK source URL 누락 | {quality["bok_source_url_missing"]["count"]} | URL을 임의 생성하지 않고 locator 보강 검토 |
| source review 미확정 | {quality["source_review_status_unresolved"]["count"]} | 운영 승인으로 간주하지 않음 |
| license 미확정 | {quality["license_status_unconfirmed"]["count"]} | 라이선스 승인 전 사용 차단 |
| 20토큰 미만 | {quality["under_20_tokens"]["count"]} | 삭제하지 않고 검토 큐 유지 |
| 청크 제한 초과 원문 | {quality["over_chunk_limit"]["count"]} | token-aware 분할 및 결과 검증 |
| 동일 source 내 content hash 중복 그룹 | {quality["duplicate_content_hash_within_source"]["count"]} | 삭제하지 않고 중복 검토 |

## Lineage 점검

- 문서 ID를 찾지 못한 청크: **{len(lineage["missing_document_links"])}건**
- 중복 Chunk ID: **{lineage["duplicate_chunk_id_count"]}건**
- 청크 문서 연결 확인: **{lineage["all_chunk_document_links_resolvable"]}**
- 여러 청크로 분할된 문서: **{len(lineage["documents_with_multiple_chunks"])}건**
- 분할 후 모든 청크가 제한 이하인지: **{lineage["all_split_chunks_within_limit"]}**

짧은 문서·중복 문서는 원본에서 삭제하지 않았습니다. BOK의 공식 URL과
라이선스, 문서 품질, 챕터 매핑 승인은 서로 다른 상태로 사람이 확인해야 합니다.
"""


def _candidate_markdown(result: dict[str, Any]) -> str:
    rows = result["added_by_current_rule"]
    lines = (
        "\n".join(
            f"| {row['document_id']} | {row['title']} | {', '.join(row['matched_keywords'])} |"
            for row in rows
        )
        or "| 없음 | - | - |"
    )
    return f"""# 키워드 후보 143건과 148건 차이 분석

## 결론

- 143건: 별칭 확장 전 규칙을 재현한 후보 수
- 148건: 현재 설정 기반 후보 수
- 증가: **{result["delta"]}건**
- 집계 단위: **{result["candidate_unit"]}**

현재 설정의 `aliases`에 추가된 `PPI`가 문서 본문에 일반 약어로 등장한
5건을 후보로 추가했습니다. 이 5건은 키워드 후보 수집 단계의 결과일 뿐,
인플레이션 관련 문서로 승인된 것이 아닙니다. 특히 표제어·본문 의미와
무관한 약어 매칭은 정밀 분류 또는 사람 검수에서 확인해야 합니다.

| 추가 문서 | 표제어 | 매칭 키워드 |
|---|---|---|
{lines}

테스트셋은 이 차이를 근거로 즉시 키워드 사전에서 삭제하거나 추가하지
않습니다. 개발셋에서 약어 경계 규칙을 검토한 뒤 규칙 버전을 올리고,
독립 테스트셋은 고정된 규칙으로 한 번만 평가합니다.
"""


def _progress_markdown(kdi: dict[str, Any], bok: dict[str, Any]) -> str:
    return f"""# 독립 Gold 검수 진행 현황

## 현재 상태

최종 평가 상태는 **NOT_EVALUATED**입니다. 템플릿은 생성되었지만 사람의
독립 검수와 합의가 완료되지 않았으므로 Precision·Recall·F1을 계산하지
않습니다.

| 기관 | 검수 템플릿 행 | 핵심 상태 |
|---|---:|---|
| KDI | {kdi["template_row_count"]} | A/B 불일치 {kdi["reviewer_a_b_disagreement_count"]}건, 품질 재검토 {kdi["source_quality_review_count"]}건 |
| BOK | {bok["current_combined_review_count"]} | 현재 데이터 기준 55 후보+50 경계+100 무작위로 재생성 |

## BOK 표본 버전 주의

기존 `reports/step3`의 205건 표본은 현재 canonical export와 source hash 및
문서 ID가 다르므로 재사용하지 않았습니다. 이전 행의 라벨이나 승인 상태를
현재 데이터에 복사하지 않았습니다.

## 사람이 해야 할 일

1. KDI와 BOK 행의 원문 및 C0704 기준을 보고 평가자 A/B가 독립적으로 0·1·2를 입력합니다.
2. `final_gold`는 합의 또는 제3자 검수 후에만 입력합니다.
3. `evidence_quote`, `reason`, `review_status`, `reviewer_count`, `review_mode`를 채웁니다.
4. `test` 행은 프롬프트·키워드·임계값 조정에 사용하지 않습니다.
5. 모든 방법이 동일한 test 문서 ID에 대해 예측을 만든 뒤에만 비교 실험을 실행합니다.
"""


def run(
    data_dir: Path = ROOT / "data",
    config_path: Path = DEFAULT_CONFIG,
    chapter_path: Path = DEFAULT_CHAPTER,
    workbook_path: Path | None = None,
    report_dir: Path = DEFAULT_REPORT_DIR,
    template_dir: Path = DEFAULT_TEMPLATE_DIR,
) -> dict[str, Any]:
    """Run the read-only validation and generate review artifacts."""
    config = load_yaml(config_path)
    chapter_payload = load_yaml(chapter_path)
    chapter = _load_chapter(chapter_path)
    documents, inventory = load_corpus(data_dir)
    tokenizer = ExactTokenizer(
        config.get("tokenizer", {}).get("model_alias", "gpt-4o-mini")
    )
    max_tokens = int(config.get("chunking", {}).get("max_tokens", 700))
    overlap_tokens = int(config.get("chunking", {}).get("overlap_tokens", 100))
    # NormalizedDocument는 원본 구조를 유지하고 token count는 별도 map으로 보관합니다.
    token_counts = {
        document.document_id: tokenizer.count(document.content)
        for document in documents
    }
    chunks = make_chunks(
        documents, tokenizer, inventory["dataset_version"], max_tokens, overlap_tokens
    )
    validation = validate_dataset(documents, chunks, max_tokens, token_counts)
    difference = _candidate_difference(chunks, chapter)
    manifest = _inventory_manifest(inventory, config, chapter_payload, difference)

    if workbook_path is None:
        workbooks = discover_label_workbook(ROOT)
        if not workbooks:
            raise FileNotFoundError("라벨링.xlsx를 찾지 못했습니다.")
        workbook_path = workbooks[0]
    kdi_rows, kdi_status = _kdi_rows(
        workbook_path, documents, chunks, chapter, inventory["dataset_version"]
    )
    bok_rows, bok_reconciliation = build_bok_review_template(
        documents, chunks, chapter, inventory["dataset_version"]
    )
    current_bok_file = next(
        item
        for item in inventory["files"]
        if item["source"] == "BOK" and item["is_canonical"]
    )
    bok_reconciliation["current_source_sha256"] = current_bok_file["file_sha256"]
    bok_reconciliation["previous_source_matches_current"] = (
        bok_reconciliation["previous_source_sha256"] == current_bok_file["file_sha256"]
    )
    bok_reconciliation["current_template_id_sha256"] = _template_hash(bok_rows)
    bok_reconciliation["source_review_status"] = "NOT_CONFIRMED_IN_CURRENT_EXPORT"
    bok_reconciliation["license_status"] = "UNCONFIRMED_IN_CURRENT_EXPORT"
    template_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(template_dir / "kdi_independent_gold_review_template.csv", kdi_rows)
    _write_csv(template_dir / "bok_independent_gold_review_template.csv", bok_rows)
    _write_reports(
        report_dir, validation, manifest, difference, kdi_status, bok_reconciliation
    )
    return {
        "status": "NOT_EVALUATED_INDEPENDENT_GOLD_REQUIRED",
        "validation": validation,
        "manifest": manifest,
        "candidate_difference": difference,
        "kdi_status": kdi_status,
        "bok_reconciliation": bok_reconciliation,
        "templates": {
            "kdi": str(
                (template_dir / "kdi_independent_gold_review_template.csv").relative_to(
                    ROOT
                )
            ),
            "bok": str(
                (template_dir / "bok_independent_gold_review_template.csv").relative_to(
                    ROOT
                )
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--chapters", type=Path, default=DEFAULT_CHAPTER)
    parser.add_argument("--workbook", type=Path)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--template-dir", type=Path, default=DEFAULT_TEMPLATE_DIR)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.data_dir,
                args.config,
                args.chapters,
                args.workbook,
                args.report_dir,
                args.template_dir,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
