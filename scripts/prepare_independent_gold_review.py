"""Prepare an unbiased Gold Label review queue and keyword-miss diagnostics.

The workbook is used only as a sampling and data-integrity reference.  Its
existing labels are never copied into the review queue and are not treated as
an independent evaluation set.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.dataset_pipeline.keywords import (  # noqa: E402
    Chapter,
    classify_chunk_by_keywords,
)
from app.dataset_pipeline.labels import (  # noqa: E402
    analyze_label_rows,
    discover_label_workbook,
    read_xlsx_rows,
)
from app.dataset_pipeline.tokenizer import ExactTokenizer  # noqa: E402
from scripts._pipeline_support import load_yaml, write_json  # noqa: E402
from scripts.rebuild_precision_pipeline import (  # noqa: E402
    _make_chunk,
    _records,
)

DEFAULT_QUEUE = ROOT / "data/labeled/precision/independent_gold_review_queue.csv"
DEFAULT_STATUS = ROOT / "reports/independent_gold_review_status.json"
DEFAULT_STATUS_REPORT = ROOT / "reports/independent_gold_review_status.md"
DEFAULT_REPORT = ROOT / "reports/keyword_miss_analysis.md"
DEFAULT_DIAGNOSTIC = ROOT / "reports/keyword_miss_analysis.json"

MANUAL_REVIEW_TERMS = (
    "기준금리",
    "상품권",
    "생산자물가지수",
    "국제피셔효과",
    "차이메리카",
    "리플레이션",
)


def _text(value: object) -> str:
    value_text = "" if value is None else str(value).strip()
    return "" if value_text.casefold() in {"", "nan", "none", "null"} else value_text


def _source_group(source: str) -> str:
    """Return a stable institution group while preserving unknown sources."""
    upper = source.upper()
    if "KDI" in upper:
        return "KDI"
    if "BOK" in upper or "한국은행" in source:
        return "BOK"
    return source or "UNKNOWN"


def _content_hash(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _split_for_review(source_group: str, document_id: str, content_hash: str) -> str:
    """Assign a reproducible 80/20 split without inspecting labels.

    The content hash is the primary grouping key so duplicate content cannot
    leak across development and test.  Document ID and source are fallbacks
    for rows where a hash could not be produced.
    """
    key_text = content_hash or f"{source_group}|{document_id}"
    key = key_text.encode("utf-8")
    bucket = int(hashlib.sha256(key).hexdigest()[:8], 16) % 10
    return "test" if bucket < 2 else "development"


def _load_inputs(
    paths: list[Path] | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    candidates = paths or discover_label_workbook(ROOT)
    if not candidates:
        raise FileNotFoundError("라벨링.xlsx 또는 라벨 파일을 찾지 못했습니다.")
    all_records: list[dict[str, Any]] = []
    analyses: list[dict[str, Any]] = []
    for path in candidates:
        rows = read_xlsx_rows(path)
        analysis = analyze_label_rows(rows, path)
        all_records.extend(_records(rows, analysis["detected_columns"]))
        analyses.append(analysis)
    return all_records, analyses


def _chapter(path: Path) -> Chapter:
    payload = load_yaml(path)
    chapters = payload.get("chapters", [])
    if not chapters:
        raise ValueError(f"{path}에 챕터가 없습니다.")
    return Chapter.from_dict(chapters[0])


def _review_stratum(record: dict[str, Any], keyword_result: dict[str, Any]) -> str:
    if record["quality"] == "검토필요" or record["quality_flag"]:
        return "source_quality_review"
    if any(
        term in record["title"] or term in record["content"]
        for term in MANUAL_REVIEW_TERMS
    ):
        return "specified_manual_review_term"
    if not keyword_result["candidate"]:
        return "keyword_non_candidate_recall_sample"
    return "keyword_candidate_precision_sample"


def _queue_rows(
    records: list[dict[str, Any]], chapter: Chapter, tokenizer: ExactTokenizer
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    queue: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for record in records:
        content_hash = _content_hash(record["content"])
        source_group = _source_group(record["source"])
        keyword_result = classify_chunk_by_keywords(
            _make_chunk(record, tokenizer), chapter
        )
        queue.append(
            {
                "document_id": record["document_id"],
                "content_hash": content_hash,
                "chunk_id": f"LABELING_XLSX:{record['document_id']}:chunk-0000",
                "source": source_group,
                "source_group": source_group,
                "source_locator": record["source_locator"],
                "title": record["title"],
                "content": record["content"],
                "chapter_id": "inflation",
                "dataset_version": "labeling-xlsx-current",
                "rubric_version": "inflation-rubric-draft-v1",
                "split": _split_for_review(
                    source_group, record["document_id"], content_hash
                ),
                "sampling_stratum": _review_stratum(record, keyword_result),
                "matched_keywords": json.dumps(
                    keyword_result["matched_keywords"], ensure_ascii=False
                ),
                "matched_keyword_types": json.dumps(
                    keyword_result["matched_keyword_types"], ensure_ascii=False
                ),
                "gold_score": "",
                "reviewer_count": "",
                "review_mode": "",
                "gold_set_status": "PENDING_INDEPENDENT_REVIEW",
                "review_status": "PENDING",
                "review_note": "",
            }
        )
        diagnostics.append(
            {
                "document_id": record["document_id"],
                "title": record["title"],
                "content": record["content"],
                "source_group": source_group,
                "reference_score_for_diagnostic_only": record["gold_score"],
                "keyword_candidate": bool(keyword_result["candidate"]),
                "matched_keywords": keyword_result["matched_keywords"],
                "matched_keyword_types": keyword_result["matched_keyword_types"],
            }
        )
    return queue, diagnostics


def _miss_category(row: dict[str, Any]) -> str:
    text = f"{row['title']} {row['content']}"
    if any(term in text for term in ("디플레이션", "디스인플레이션", "물가 하락")):
        return "opposite_concept_missing"
    if any(term in text for term in ("인플레", "물가", "가격 상승", "CPI", "PPI")):
        return "core_or_alias_missing"
    if any(
        term in text
        for term in (
            "금리",
            "통화",
            "화폐",
            "구매력",
            "중앙은행",
            "소득",
            "소비",
            "가격",
            "지수",
            "환율",
        )
    ):
        return "related_concept_or_chapter_boundary"
    return "chapter_boundary_or_reference_label_review"


def _diagnostic_report(
    diagnostics: list[dict[str, Any]], analyses: list[dict[str, Any]]
) -> dict[str, Any]:
    misses = [
        row
        for row in diagnostics
        if row["reference_score_for_diagnostic_only"] in {1, 2}
        and not row["keyword_candidate"]
    ]
    categories = Counter(_miss_category(row) for row in misses)
    suggestions = Counter(row["title"] for row in misses if row["title"])
    candidate_count = sum(row["keyword_candidate"] for row in diagnostics)
    return {
        "status": "REFERENCE_DIAGNOSTIC_ONLY",
        "warning": (
            "현재 확정 골드는 독립 Gold가 아니므로 성능·테스트 튜닝에 사용하지 않음"
        ),
        "total_documents": len(diagnostics),
        "keyword_candidate_count": candidate_count,
        "keyword_candidate_rate": candidate_count / len(diagnostics)
        if diagnostics
        else 0.0,
        "reference_positive_misses_count": len(misses),
        "reference_positive_misses_by_score": dict(
            Counter(row["reference_score_for_diagnostic_only"] for row in misses)
        ),
        "miss_categories": dict(categories),
        "proposed_terms_from_missed_titles": [
            {"term": term, "count": count, "status": "HUMAN_REVIEW_REQUIRED"}
            for term, count in suggestions.most_common(30)
        ],
        "source_distribution": dict(
            Counter(row["source_group"] for row in diagnostics)
        ),
        "reviewer_disagreement_count": sum(
            len(analysis.get("disagreements", [])) for analysis in analyses
        ),
        "quality_review_row_count": sum(
            analysis.get("integrity", {})
            .get("quality_distribution", {})
            .get("검토필요", 0)
            for analysis in analyses
        ),
        "miss_examples": [
            {
                "document_id": row["document_id"],
                "title": row["title"],
                "reference_score_for_diagnostic_only": row[
                    "reference_score_for_diagnostic_only"
                ],
                "category": _miss_category(row),
            }
            for row in misses[:100]
        ],
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else []
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _markdown(status: dict[str, Any], diagnostic: dict[str, Any]) -> str:
    suggestions = diagnostic["proposed_terms_from_missed_titles"][:20]
    suggestion_lines = "\n".join(
        f"| {item['term']} | {item['count']} | 사람 검토 필요 |"
        for item in suggestions
    ) or "| 없음 | 0 | - |"
    category_lines = "\n".join(
        f"| {key} | {value} |" for key, value in diagnostic["miss_categories"].items()
    ) or "| 없음 | 0 |"
    return f"""# 독립 Gold 검수 준비 및 키워드 누락 분석

## 핵심 결론

- 현재 상태: **`NOT_EVALUATED`**
- 입력 문서: **{diagnostic['total_documents']}건**
- 키워드 후보: **{diagnostic['keyword_candidate_count']}건**
- 기존 참고 라벨 기준 미매칭 관련 후보:
  **{diagnostic['reference_positive_misses_count']}건**
- 이 보고서의 기존 라벨 수치는 독립 Gold가 아니므로
  Precision·Recall·F1로 보고하지 않습니다.

## 독립 Gold 검수 큐

- 검수 큐: `{DEFAULT_QUEUE.relative_to(ROOT)}`
- `gold_score`는 비워 두었으며 평가자 합의 후에만 입력합니다.
- `review_status=APPROVED`, `gold_set_status=INDEPENDENT_APPROVED`이고,
  합의 검수 2명 이상 또는 제3자 검수가 확인된 행만 최종 평가에 사용합니다.
- `development`와 `test`는 Document ID·Content Hash·출처 그룹의 안정 해시로
  분리했습니다.
- 검수자는 기존 평가자 A/B 라벨을 보지 않는 것을 원칙으로 합니다.

## 현재 파일 점검 요약

- 평가자 A/B 불일치: **{diagnostic['reviewer_disagreement_count']}건**
- 지정 수동 검토 용어가 포함된 행: **{diagnostic['quality_review_row_count']}건**
- 출처 그룹 분포: `{diagnostic['source_distribution']}`

## 키워드 미매칭 진단(참고 라벨 전용)

| 미매칭 원인 가설 | 건수 |
|---|---:|
{category_lines}

후보 제목에서 추출한 확장 후보는 자동 반영하지 않습니다. 독립 테스트셋을
키워드 확장이나 임계값 조정에 사용하지 않도록, 아래 항목은 개발셋에서 별도
검토한 뒤 설정 파일에 반영해야 합니다.

| 후보 용어 | 미매칭 행 수 | 처리 |
|---|---:|---|
{suggestion_lines}

## 다음 단계

1. 검수 큐에서 개발셋과 테스트셋을 각각 독립적으로 평가합니다.
2. 불일치 10건과 자료 품질 검토 대상은 합의 또는 제3자 검수로 확정합니다.
3. 개발셋으로 키워드 사전과 프롬프트를 고정합니다.
4. 테스트셋은 고정된 설정으로 Keyword-only, LLM-only, Hybrid를 실행합니다.
5. 세 방법 모두 전체 테스트 ID에 대한 예측이 있을 때만 지표를 계산합니다.
"""


def _status_markdown(status: dict[str, Any]) -> str:
    """Render the review state without exposing the workbook's old labels."""
    return f"""# 독립 Gold 검수 상태

## 현재 상태

- 평가 상태: **`{status['status']}`**
- 사유: {status['reason']}
- 검수 큐: `{status['review_queue']}`
- 검수 행 수: **{status['queue_row_count']}건**
- 개발셋/테스트셋: `{status['split_counts']}`
- 출처 그룹: `{status['source_groups_supported_by_queue']}`
- 현재 입력의 BOK 포함 여부: **{status['bok_present_in_current_input']}**

## 독립성 보호 규칙

- 기존 평가자 A/B 및 확정 골드는 검수 큐에 복사하지 않았습니다.
- `gold_score`는 사람이 원문과 챕터 기준을 확인한 뒤 입력합니다.
- 합의 검수 2명 이상 또는 제3자 검수 1명 이상만 승인할 수 있습니다.
- `INDEPENDENT_APPROVED`와 `APPROVED`가 아닌 행은 최종 평가에서 제외됩니다.
- 테스트셋은 키워드·프롬프트·임계값 조정에 사용하지 않습니다.

## 검수 전 차단 상태

독립 Gold가 생성되기 전까지 세 방법의 Precision·Recall·F1과
최종 성능 지표는 `NOT_EVALUATED`로 유지됩니다. 일부 방법의 예측이
빠진 경우에도 교집합만으로 지표를 계산하지 않습니다.
"""


def run(
    workbook_paths: list[Path] | None = None,
    chapter_path: Path = ROOT / "configs/chapters.yaml",
    queue_path: Path = DEFAULT_QUEUE,
    status_path: Path = DEFAULT_STATUS,
    status_report_path: Path = DEFAULT_STATUS_REPORT,
    report_path: Path = DEFAULT_REPORT,
    diagnostic_path: Path = DEFAULT_DIAGNOSTIC,
) -> dict[str, Any]:
    """Create review artifacts without copying the workbook labels."""
    records, analyses = _load_inputs(workbook_paths)
    chapter = _chapter(chapter_path)
    tokenizer = ExactTokenizer("gpt-4o-mini")
    queue, diagnostics = _queue_rows(records, chapter, tokenizer)
    diagnostic = _diagnostic_report(diagnostics, analyses)
    split_counts = Counter(row["split"] for row in queue)
    source_split_counts: dict[str, dict[str, int]] = {}
    for row in queue:
        source_split_counts.setdefault(row["source_group"], Counter())[
            row["split"]
        ] += 1
    status = {
        "status": "NOT_EVALUATED",
        "reason": "독립 합의 Gold가 아직 생성되지 않았습니다.",
        "queue_row_count": len(queue),
        "split_counts": dict(split_counts),
        "source_split_counts": {
            source: dict(counts) for source, counts in source_split_counts.items()
        },
        "source_groups_supported_by_queue": sorted(source_split_counts),
        "bok_present_in_current_input": "BOK" in source_split_counts,
        "duplicate_document_ids": [
            document_id
            for document_id, count in Counter(
                row["document_id"] for row in queue
            ).items()
            if count > 1
        ],
        "duplicate_content_hashes": [
            content_hash
            for content_hash, count in Counter(
                row["content_hash"] for row in queue
            ).items()
            if count > 1
        ],
        "diagnostic_report": str(diagnostic_path.relative_to(ROOT)),
        "review_queue": str(queue_path.relative_to(ROOT)),
        "status_report": str(status_report_path.relative_to(ROOT)),
        "gold_labels_copied_from_workbook": False,
    }
    _write_csv(queue_path, queue)
    write_json(status_path, status)
    write_json(diagnostic_path, diagnostic)
    status_report_path.parent.mkdir(parents=True, exist_ok=True)
    status_report_path.write_text(_status_markdown(status), encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_markdown(status, diagnostic), encoding="utf-8")
    return {"status": status, "diagnostic": diagnostic}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, action="append")
    parser.add_argument("--chapters", type=Path, default=ROOT / "configs/chapters.yaml")
    parser.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    parser.add_argument("--status", type=Path, default=DEFAULT_STATUS)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--diagnostic", type=Path, default=DEFAULT_DIAGNOSTIC)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                args.workbook,
                args.chapters,
                args.queue,
                args.status,
                DEFAULT_STATUS_REPORT,
                args.report,
                args.diagnostic,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
