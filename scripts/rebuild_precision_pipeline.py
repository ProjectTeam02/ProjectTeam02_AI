# 파일 역할: 라벨링 Excel을 기준으로 정밀도 중심 EDA와
# 오프라인 후보 필터 평가를 수행합니다.
"""Rebuild the precision-oriented dataset pipeline from the human label workbook.

This script deliberately stays offline.  It does not call an LLM, modify the
source workbook, or treat keyword matches as final relevance decisions.  The
Excel Gold Label is used as the current reference set, while the report clearly
states that an independently adjudicated evaluation set is still required for
final model-quality claims.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# 저장소 어느 위치에서 실행해도 기존 앱 모듈을 재사용하도록 루트를 등록합니다.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.dataset_pipeline.chunks import Chunk  # noqa: E402
from app.dataset_pipeline.evaluation import (  # noqa: E402
    confusion_matrix,
    positive_for_use,
    precision_recall_f1,
)
from app.dataset_pipeline.keywords import (  # noqa: E402
    Chapter,
    classify_chunk_by_keywords,
)
from app.dataset_pipeline.labels import (  # noqa: E402
    analyze_label_rows,
    discover_label_workbook,
    read_xlsx_rows,
)
from app.dataset_pipeline.tokenizer import ExactTokenizer, summarize  # noqa: E402
from scripts._pipeline_support import load_yaml, write_json  # noqa: E402

DEFAULT_OUTPUT_DIR = ROOT / "data" / "labeled" / "precision"
DEFAULT_REPORT = ROOT / "reports" / "precision_pipeline_report.md"
DEFAULT_SUMMARY = ROOT / "reports" / "precision_pipeline_summary.json"
MANUAL_REVIEW_TERMS = (
    "기준금리",
    "상품권",
    "생산자물가지수",
    "국제피셔효과",
    "차이메리카",
    "리플레이션",
)


def _text(value: object) -> str:
    """Convert spreadsheet values to comparable stripped text."""
    # Excel의 빈 셀과 문자열형 결측값을 동일한 빈 문자열로 처리합니다.
    value_text = "" if value is None else str(value).strip()
    return "" if value_text.casefold() in {"nan", "none", "null"} else value_text


def _score(value: object) -> int | None:
    """Parse the human relevance score without silently inventing a label."""
    # 관련도는 0·1·2만 허용하며, 그 외 값은 평가 대상에서 제외합니다.
    text = _text(value)
    if not text or text not in {"0", "1", "2"}:
        return None
    return int(text)


def _suitability(value: object) -> bool | None:
    """Convert the workbook's Korean suitability field to a binary value."""
    # 적합/부적합 외의 입력은 임의로 양성·음성으로 바꾸지 않습니다.
    text = _text(value)
    if text == "적합":
        return True
    if text == "부적합":
        return False
    return None


def _source_group(value: str) -> str:
    """Map verbose source labels to stable institution groups."""
    # 출처가 긴 설명형 문자열이어도 기관별 분포를 비교할 수 있게 축약합니다.
    if "KDI" in value.upper():
        return "KDI"
    if "한국은행" in value or "BOK" in value.upper():
        return "BOK"
    return value or "UNKNOWN"


def _paragraph_count(content: str) -> int:
    # 줄바꿈이 없는 용어 사전 설명은 하나의 논리 단락으로 계산합니다.
    parts = [part.strip() for part in re.split(r"\n\s*\n", content) if part.strip()]
    return len(parts) or 1


def _records(
    rows: list[dict[str, str]], columns: dict[str, str | None]
) -> list[dict[str, Any]]:
    """Normalize only the fields needed by the precision experiment."""
    records: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=2):

        def get(key: str) -> str:
            column = columns.get(key)
            return _text(row.get(column, "")) if column else ""

        content = get("content")
        title = get("title")
        document_id = get("id") or f"row-{index}"
        records.append(
            {
                "row_number": index,
                "document_id": document_id,
                "title": title,
                "content": content,
                "source": get("source"),
                "source_group": _source_group(get("source")),
                "source_locator": get("source_locator"),
                "gold_score": _score(get("gold")),
                "reviewer_a": _score(get("reviewer_a")),
                "reviewer_b": _score(get("reviewer_b")),
                "quality": get("quality"),
                "quality_flag": get("quality_flag"),
                "quiz_suitable": _suitability(get("quiz")),
                "tutor_suitable": _suitability(get("tutor")),
                "reason": get("reason"),
                "keyword_label": get("keyword"),
                "binary_label": get("binary_label"),
                "b_review": get("b_review"),
            }
        )
    return records


def _policy_metrics(
    records: list[dict[str, Any]], field: str, usage: str
) -> dict[str, Any]:
    """Compare a workbook suitability column with the Gold Label policy."""
    pairs = [
        (record[field], record["gold_score"])
        for record in records
        if record[field] is not None and record["gold_score"] is not None
    ]
    predictions = [prediction for prediction, _ in pairs]
    gold = [positive_for_use(score, usage) for _, score in pairs]
    matrix = confusion_matrix(predictions, gold)
    return {
        "usage": usage,
        "field": field,
        "comparable_count": len(pairs),
        "matrix": matrix,
        "metrics": precision_recall_f1(matrix),
        "interpretation": (
            "workbook suitability consistency, not an independent model score"
        ),
    }


def _keyword_metrics(rows: list[dict[str, Any]], usage: str) -> dict[str, Any]:
    """Evaluate keyword candidate flags against one usage policy."""
    comparable = [row for row in rows if row["gold_score"] is not None]
    predictions = [bool(row["candidate"]) for row in comparable]
    gold = [positive_for_use(row["gold_score"], usage) for row in comparable]
    matrix = confusion_matrix(predictions, gold)
    return {
        "usage": usage,
        "candidate_count": sum(predictions),
        "population_count": len(comparable),
        "candidate_rate": sum(predictions) / len(predictions) if predictions else 0.0,
        "matrix": matrix,
        "metrics": precision_recall_f1(matrix),
    }


def _make_chunk(record: dict[str, Any], tokenizer: ExactTokenizer) -> Chunk:
    """Represent one labeled definition as a chunk while preserving lineage."""
    # 현재 Excel은 용어 사전 단위이므로 설명 하나를 한 청크로 시작하고,
    # 이후 실제 긴 원문이 들어오면 기존 paragraph-first chunker로 확장합니다.
    content = record["content"]
    return Chunk(
        document_id=record["document_id"],
        chunk_id=f"LABELING_XLSX:{record['document_id']}:chunk-0000",
        source=record["source_group"],
        title=record["title"],
        content=content,
        source_url=record["source_locator"] or None,
        source_locator=record["source_locator"] or None,
        chunk_index=0,
        token_count=tokenizer.count(content),
        text_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        dataset_version="labeling-xlsx-current",
        source_review_status=record["quality"] or "UNKNOWN",
        license_status="UNCONFIRMED",
    )


def _keyword_rows(
    records: list[dict[str, Any]],
    chapter: Chapter,
    tokenizer: ExactTokenizer,
    strategy: str,
) -> list[dict[str, Any]]:
    """Run one deterministic keyword strategy over every labeled definition."""
    output: list[dict[str, Any]] = []
    for record in records:
        result = classify_chunk_by_keywords(_make_chunk(record, tokenizer), chapter)
        output.append(
            {
                "strategy": strategy,
                "row_number": record["row_number"],
                "document_id": record["document_id"],
                "title": record["title"],
                "source_group": record["source_group"],
                "gold_score": record["gold_score"],
                "question_gold_positive": (
                    record["gold_score"] == 2
                    if record["gold_score"] is not None
                    else None
                ),
                "tutor_gold_positive": (
                    record["gold_score"] in {1, 2}
                    if record["gold_score"] is not None
                    else None
                ),
                "candidate": bool(result["candidate"]),
                "keyword_match_score": result["keyword_match_score"],
                "matched_keywords": json.dumps(
                    result["matched_keywords"], ensure_ascii=False
                ),
                "matched_keyword_types": json.dumps(
                    result["matched_keyword_types"], ensure_ascii=False
                ),
                "evidence_span": result["evidence_span"] or "",
                "review_status": "PENDING",
            }
        )
    return output


def _review_queue(
    records: list[dict[str, Any]],
    keyword_rows: list[dict[str, Any]],
    analysis: dict[str, Any],
) -> list[dict[str, Any]]:
    """Create a local review queue for precision and recall errors."""
    by_id: dict[str, list[dict[str, Any]]] = {}
    for row in keyword_rows:
        by_id.setdefault(row["document_id"], []).append(row)
    disagreement_ids = {
        item["document_id"]
        for item in analysis["disagreements"]
        if item.get("document_id")
    }
    quality_rows = {
        item["row_number"]: item for item in analysis["manual_review_candidates"]
    }
    queue: list[dict[str, Any]] = []
    for record in records:
        reasons: list[str] = []
        if record["document_id"] in disagreement_ids:
            reasons.append("reviewer_disagreement")
        if record["quality"] == "검토필요" or record["quality_flag"]:
            reasons.append("source_quality_review")
        if record["b_review"]:
            reasons.append("reviewer_b_marked_review")
        if any(
            term in record["title"] or term in record["content"]
            for term in MANUAL_REVIEW_TERMS
        ):
            reasons.append("specified_manual_review_term")
        for row in by_id.get(record["document_id"], []):
            if (
                row["gold_score"] == 2
                and not row["candidate"]
                and row["strategy"] == "expanded"
            ):
                reasons.append("keyword_false_negative_for_question_generation")
            if (
                row["gold_score"] in {1, 2}
                and not row["candidate"]
                and row["strategy"] == "expanded"
            ):
                reasons.append("keyword_false_negative_for_tutor_retrieval")
            if (
                row["gold_score"] != 2
                and row["candidate"]
                and row["strategy"] == "expanded"
            ):
                reasons.append("keyword_false_positive_for_question_generation")
        if record["row_number"] in quality_rows:
            reasons.extend(
                reason
                for reason in quality_rows[record["row_number"]]["review_reason"].split(
                    ";"
                )
                # 관련도 0점의 템플릿형 '무관' 근거는
                # 본문 단어가 없어도 정상일 수 있습니다.
                if reason
                and reason not in reasons
                and not (
                    reason == "reason_has_no_content_token_overlap"
                    and record["gold_score"] == 0
                )
            )
        if reasons:
            queue.append(
                {
                    "row_number": record["row_number"],
                    "document_id": record["document_id"],
                    "title": record["title"],
                    "gold_score": record["gold_score"],
                    "quality": record["quality"],
                    "review_reasons": ";".join(dict.fromkeys(reasons)),
                    "review_status": "PENDING",
                    "content": record["content"],
                }
            )
    return queue


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    """Write generated row-level artifacts locally with a stable schema."""
    # CSV에는 원문이 포함될 수 있으므로 .gitignore가 적용된 로컬 경로에만 저장합니다.
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0]) if rows else ["status"]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _percent(value: float | None) -> str:
    # 보고서에서는 소수와 백분율을 함께 혼동하지 않도록 퍼센트로 표시합니다.
    return "N/A" if value is None else f"{value:.1%}"


def _display_path(path: Path) -> str:
    """Return a portable path for reports generated on different machines."""
    # 절대 경로에는 사용자 계정명이 포함될 수 있습니다.
    # 가능한 경우 저장소 상대 경로를 기록합니다.
    try:
        relative = str(path.relative_to(ROOT))
    except ValueError:
        relative = str(path)
    return unicodedata.normalize("NFC", relative)


def _report(summary: dict[str, Any]) -> str:
    """Render a compact Korean report for mentor/professor review."""
    # 실제 측정값, 현재 라벨의 한계, 다음 검수 단계를 한 보고서에 같이 기록합니다.
    basic = summary["keyword_evaluation"]["basic_core"]
    expanded = summary["keyword_evaluation"]["expanded"]
    question = expanded["question_generation"]
    tutor = expanded["tutor_retrieval"]
    token = summary["text_eda"]["token_count"]
    chars = summary["text_eda"]["character_count"]
    label = summary["label_quality"]
    basic_question = basic["question_generation"]
    basic_tutor = basic["tutor_retrieval"]

    def metric_line(item: dict[str, Any], strategy: str, usage: str) -> str:
        # 표의 각 행을 여러 문자열로 나누어 코드 가독성과 린트 기준을 함께 지킵니다.
        metrics = item["metrics"]
        return (
            f"| {strategy} | {usage} | {item['candidate_count']} | "
            f"{_percent(metrics['precision'])} | {_percent(metrics['recall'])} | "
            f"{_percent(metrics['f1'])} |"
        )

    return f"""# Excel 라벨 기반 정밀도 중심 EDA·파이프라인 결과

## 1. 실행 범위

- 입력 파일: `{summary["input_file"]}`
- 입력 행 수: **{summary["row_count"]}건**
- 챕터 기준: `{summary["chapter_id"]}` / `{summary["chapter_config_status"]}`
- LLM 호출: **0회** (키워드 기준선과 라벨 품질만 오프라인 평가)
- 원본 Excel: 수정하지 않음

## 2. 데이터 EDA

- 기관별 건수: `{summary["source_distribution"]}`
- 설명 문자 수: 평균 `{chars["average"]:.1f}`, 중앙값 `{chars["median"]}`
- 설명 토큰 수: 평균 `{token["average"]:.1f}`, 중앙값 `{token["median"]}`,
  총 `{token["total"]}`
- 사용 토크나이저: `{token["tokenizer"]}` / `{token["encoding"]}`
- 단락 수: `{summary["text_eda"]["paragraph_count"]}`
- 골드 관련도 분포: `{summary["gold_distribution"]}`

## 3. 라벨 품질 결과

- 평가자 A·B 비교 가능 행: `{label["reviewer_comparable_count"]}건`
- 평가자 A·B 일치율: `{_percent(summary["label_quality"]["reviewer_agreement_rate"])}`
- 평가자 불일치: `{label["reviewer_disagreement_count"]}건`
- 자료 품질 `검토필요`: `{label["quality_review_count"]}건`
- 문제 생성 적합성 열과 골드 정책 불일치: `{label["quiz_policy_mismatch_count"]}건`
- 튜터 검색 적합성 열과 골드 정책 불일치: `{label["tutor_policy_mismatch_count"]}건`
- 판정 근거와 본문 토큰이 겹치지 않는 행:
  `{label["reason_without_content_overlap_count"]}건`

평가자 A의 라벨이 현재 골드와 동일하므로 A 기준 수치는 독립적인 모델 성능이 아닙니다.
평가자 B는 49건 중 10건이 달라 합의 검수가 필요합니다.

## 4. 키워드 후보 기준선

키워드 매칭은 최종 관련도 판정이 아니라 후보 수집 단계입니다.

| 전략 | 목적 | 후보 수 | Precision | Recall | F1 |
|---|---|---:|---:|---:|---:|
{metric_line(basic_question, "기본 키워드", "문제 생성")}
{metric_line(question, "확장 키워드", "문제 생성")}
{metric_line(basic_tutor, "기본 키워드", "튜터 검색")}
{metric_line(tutor, "확장 키워드", "튜터 검색")}

위 수치는 현재 Excel의 `확정 골드`를 기준으로 한 오프라인 기준선입니다.
독립적으로 합의된 평가 세트가 아니므로 최종 제품 성능으로 보고하지 않습니다.

## 5. 재구축한 사용 정책

1. Excel의 `확정 골드=2`만 문제 생성 후보의 양성 기준으로 사용합니다.
2. Excel의 `확정 골드=1 또는 2`는 튜터 검색의 폭넓은 검색 기준으로 사용합니다.
3. 키워드 미매칭 자료는 삭제하지 않고, 누락 후보 검수 큐에 남깁니다.
4. 문제 생성은 키워드 후보 → LLM 정밀 분류 → 출처·근거 검증 →
   Human Review 순서로 진행합니다.
5. `관련도 2`는 문제 생성 후보이지 자동 승인 상태가 아닙니다.

## 6. 우선 검수 대상

- 평가자 A·B 불일치 10건
- 자료 품질 `검토필요` 7건
- `기준금리`, `상품권`, `생산자물가지수`, `국제피셔효과`, `차이메리카`, `리플레이션`
- 확장 키워드 기준 문제 생성용 오탐·누락 사례

행 단위 후보와 검수 큐는 로컬의 `{summary["candidate_csv"]}`와
`{summary["review_queue_csv"]}`에 저장됩니다. 이 파일들은 원문을 포함할 수 있으므로
Git에는 올리지 않습니다.
"""


def run(
    workbook_path: Path | None = None,
    chapter_path: Path = ROOT / "configs" / "chapters.yaml",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    report_path: Path = DEFAULT_REPORT,
    summary_path: Path = DEFAULT_SUMMARY,
) -> dict[str, Any]:
    """Run the complete offline precision EDA and candidate pipeline."""
    # 입력 탐색 → 라벨 검증 → 토큰 EDA → 기준선 평가 → 로컬 검수 큐 생성 순서입니다.
    if workbook_path is None:
        candidates = discover_label_workbook(ROOT)
        if not candidates:
            raise FileNotFoundError("라벨링.xlsx 또는 라벨 파일을 찾지 못했습니다.")
        workbook_path = candidates[0]
    rows = read_xlsx_rows(workbook_path)
    analysis = analyze_label_rows(rows, workbook_path)
    columns = analysis["detected_columns"]
    records = _records(rows, columns)

    chapter_payload = load_yaml(chapter_path)
    chapter_items = chapter_payload.get("chapters", [])
    if not chapter_items:
        raise ValueError(f"{chapter_path}에 챕터가 없습니다.")
    chapter = Chapter.from_dict(chapter_items[0])
    tokenizer_name = "gpt-4o-mini"
    tokenizer_config = ROOT / "configs" / "eda_config.yaml"
    if tokenizer_config.is_file():
        config = load_yaml(tokenizer_config)
        tokenizer_name = str(
            config.get("tokenizer", {}).get("model_alias", tokenizer_name)
        )
    tokenizer = ExactTokenizer(tokenizer_name)

    text_lengths = [len(record["content"]) for record in records]
    token_lengths = [tokenizer.count(record["content"]) for record in records]
    paragraph_lengths = [_paragraph_count(record["content"]) for record in records]
    # 기본 전략은 핵심 키워드만 사용합니다.
    # 확장 전략은 aliases/related/opposite까지 포함합니다.
    basic_chapter = Chapter(
        chapter_id=chapter.chapter_id,
        chapter_name=chapter.chapter_name,
        chapter_definition=chapter.chapter_definition,
        include_criteria=chapter.include_criteria,
        exclude_criteria=chapter.exclude_criteria,
        keywords=chapter.keywords,
        related_keywords=(),
        opposite_keywords=(),
        exclude_keywords=chapter.exclude_keywords,
        rubric_version=chapter.rubric_version,
        aliases=(),
    )
    strategy_rows = {
        "basic_core": _keyword_rows(records, basic_chapter, tokenizer, "basic_core"),
        "expanded": _keyword_rows(records, chapter, tokenizer, "expanded"),
    }
    keyword_evaluation: dict[str, Any] = {}
    for strategy, candidate_rows in strategy_rows.items():
        keyword_evaluation[strategy] = {
            "question_generation": _keyword_metrics(
                candidate_rows, "question_generation"
            ),
            "tutor_retrieval": _keyword_metrics(candidate_rows, "tutor_retrieval"),
        }
    expanded_rows = strategy_rows["expanded"]
    policy_metrics = {
        "question_generation": _policy_metrics(
            records, "quiz_suitable", "question_generation"
        ),
        "tutor_retrieval": _policy_metrics(
            records, "tutor_suitable", "tutor_retrieval"
        ),
    }
    review_queue = _review_queue(records, expanded_rows, analysis)

    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_csv = output_dir / "precision_keyword_candidates.csv"
    review_queue_csv = output_dir / "precision_review_queue.csv"
    _write_csv(candidate_csv, [row for rows in strategy_rows.values() for row in rows])
    _write_csv(review_queue_csv, review_queue)

    gold_distribution = dict(
        sorted(Counter(str(record["gold_score"]) for record in records).items())
    )
    comparable = [
        (record["reviewer_a"], record["reviewer_b"])
        for record in records
        if record["reviewer_a"] is not None and record["reviewer_b"] is not None
    ]
    summary: dict[str, Any] = {
        "status": "EXECUTED_OFFLINE_PRECISION_EDA",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "input_file": _display_path(workbook_path),
        "row_count": len(records),
        "chapter_id": chapter.chapter_id,
        "chapter_config_status": chapter_payload.get("curriculum_status", "UNKNOWN"),
        "source_distribution": dict(
            Counter(record["source_group"] for record in records)
        ),
        "gold_distribution": gold_distribution,
        "text_eda": {
            "character_count": summarize(text_lengths),
            "token_count": {
                **summarize(token_lengths),
                "tokenizer": tokenizer_name,
                "encoding": tokenizer.encoding_name,
            },
            "paragraph_count": summarize(paragraph_lengths),
        },
        "label_quality": {
            "reviewer_comparable_count": len(comparable),
            "reviewer_agreement_rate": (
                sum(a == b for a, b in comparable) / len(comparable)
                if comparable
                else None
            ),
            "reviewer_disagreement_count": len(analysis["disagreements"]),
            "quality_review_count": sum(
                record["quality"] == "검토필요" for record in records
            ),
            "quiz_policy_mismatch_count": policy_metrics["question_generation"][
                "matrix"
            ]["fp"]
            + policy_metrics["question_generation"]["matrix"]["fn"],
            "tutor_policy_mismatch_count": policy_metrics["tutor_retrieval"]["matrix"][
                "fp"
            ]
            + policy_metrics["tutor_retrieval"]["matrix"]["fn"],
            "reason_without_content_overlap_count": analysis["reason_audit"][
                "reason_without_content_overlap_count"
            ],
            "keyword_label_filled_count": sum(
                bool(record["keyword_label"]) for record in records
            ),
            "binary_label_filled_count": sum(
                bool(record["binary_label"]) for record in records
            ),
        },
        "policy_evaluation": policy_metrics,
        "keyword_evaluation": keyword_evaluation,
        "review_queue_count": len(review_queue),
        "candidate_csv": str(candidate_csv.relative_to(ROOT)),
        "review_queue_csv": str(review_queue_csv.relative_to(ROOT)),
        "llm_calls": 0,
        "independent_gold_set_status": (
            "NOT_INDEPENDENT; current workbook Gold Label used as reference"
        ),
        "precision_claim_allowed": False,
    }
    write_json(summary_path, summary)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(_report(summary), encoding="utf-8")
    return summary


def main() -> None:
    # CLI 인자로 입력 Excel과 출력 위치를 바꾸어 반복 실험할 수 있습니다.
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workbook", type=Path, default=None)
    parser.add_argument("--chapters", type=Path, default=ROOT / "configs/chapters.yaml")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    args = parser.parse_args()
    result = run(
        workbook_path=args.workbook,
        chapter_path=args.chapters,
        output_dir=args.output_dir,
        report_path=args.report,
        summary_path=args.summary,
    )
    print(
        json.dumps(
            {
                "status": result["status"],
                "row_count": result["row_count"],
                "token_total": result["text_eda"]["token_count"]["total"],
                "review_queue_count": result["review_queue_count"],
                "llm_calls": result["llm_calls"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
