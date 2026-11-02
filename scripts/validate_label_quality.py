# 파일 역할: 라벨링.xlsx의 무결성·일관성·검수 후보를 생성합니다.
"""Validate the existing human-label workbook without changing the source."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

# 스크립트를 어느 현재 디렉터리에서 실행해도 저장소 루트를 기준으로 동작합니다.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.dataset_pipeline.labels import (  # noqa: E402
    analyze_label_rows,
    discover_label_workbook,
    read_xlsx_rows,
)

REPORT_DIR = ROOT / "reports"
# 사용자가 제공한 참고값입니다. 실제 파일이 없을 때 결과값으로 사용하지 않습니다.
REFERENCE_COUNTS = {
    "document_count": 160,
    "relevance_0": 98,
    "relevance_1": 55,
    "relevance_2": 7,
    "reviewer_b_filled": 49,
    "reviewer_disagreements": 10,
    "quality_review_needed": 7,
}


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    """Write UTF-8 CSV while preserving an explicit schema for empty results."""
    # 결과 행이 0건이어도 헤더를 남겨 후속 검수 도구가 같은 형식으로 읽게 합니다.
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=fields, extrasaction="ignore", lineterminator="\n"
        )
        writer.writeheader()
        writer.writerows(rows)


def unavailable_result(candidates: list[Path]) -> dict[str, Any]:
    """Represent missing input explicitly instead of copying reference numbers."""
    # 파일 부재를 '문제 없음'으로 오해하지 않도록 실제 지표를 None으로 기록합니다.
    return {
        "status": "NOT_AVAILABLE",
        "input_file": None,
        "searched_candidate_paths": [str(path) for path in candidates],
        "actual_metrics": None,
        "reference_metrics_not_verified": REFERENCE_COUNTS,
        "reason": "라벨링.xlsx를 저장소와 작업 폴더에서 찾지 못했습니다.",
    }


def report_markdown(result: dict[str, Any]) -> str:
    """Render the quality result for mentor and professor review."""
    # 멘토 검토 시 실제 실행 결과와 아직 실행하지 못한 항목을 한눈에 구분합니다.
    if result["status"] == "NOT_AVAILABLE":
        return """# 라벨링 데이터 품질 검증 보고서

## 실행 상태

- 상태: `NOT_AVAILABLE`
- `라벨링.xlsx`가 현재 저장소와 작업 폴더에 없어 실제 검사를 수행하지 못했습니다.
- 요청문에 제시된 160건 및 라벨 분포는 참고값으로만 보관했으며,
  실제 결과로 복사하지 않았습니다.
- 파일이 추가되면 다음 명령으로 동일 검사를 재실행할 수 있습니다.

```bash
python scripts/validate_label_quality.py
```

## 현재 확인할 수 없는 항목

중복 원문ID, 빈 표제어·설명, 출처 누락, 문자 수 불일치, 원문 품질 플래그,
0·1·2점 유효성, 평가자 A·B 일치율, 확정 골드 비교, 판정 근거 반복 및
수동 재검토 후보를 아직 산출할 수 없습니다.

## 다음 조치

`라벨링.xlsx`를 `data/labeled/` 또는 저장소 루트에 넣고 다시 실행합니다.
원본 파일은 수정하지 않으며, 검사 결과만 `reports/`에 기록합니다.
"""
    integrity = result["integrity"]
    consistency = result["label_consistency"]
    return f"""# 라벨링 데이터 품질 검증 보고서

## 실행 상태

- 상태: `EXECUTED`
- 입력 파일: `{result["source_path"]}`
- 검사 행 수: **{result["row_count"]}건**

## 무결성 검사

- 중복 원문ID: `{len(integrity["duplicate_ids"])}`개 ID
- 빈 표제어: `{integrity["empty_title_count"]}건`
- 빈 설명: `{integrity["empty_content_count"]}건`
- 출처 누락: `{integrity["missing_source_count"]}건`
- 문자 수 불일치: `{len(integrity["char_count_mismatch_rows"])}건`
- 유효하지 않은 관련도: `{len(integrity["invalid_relevance_values"])}건`
- 원문 품질 플래그 누락: `{integrity["quality_flag_missing_count"]}건`
- 대체문자(�) 포함 셀: `{integrity["replacement_character_count"]}건`

## 라벨 일관성

- 평가자 A·B 비교: `{consistency["reviewer_agreement"]}`
- 평가자 불일치: `{consistency["disagreement_count"]}건`
- 관련도 분포: `{consistency["relevance_distribution"]}`
- 평가자 A와 골드 불일치: `{consistency["gold_vs_reviewer_a_mismatch_count"]}건`
- 평가자 B와 골드 불일치: `{consistency["gold_vs_reviewer_b_mismatch_count"]}건`

## 판정 근거

- 반복 근거: `{result["reason_audit"]["repeated_reasons"]}`
- 본문에서 근거 문장을 그대로 찾지 못한 후보:
  `{result["reason_audit"]["reason_not_found_candidate_count"]}건`

## 검수 원칙

기준금리, 상품권, 생산자물가지수, 국제피셔효과, 차이메리카, 리플레이션은
자동 확정하지 않고 `label_review_candidates.csv`에서 사람이 재검토합니다.
문제 생성용 양성 라벨은 관련도 2점이라는 이유만으로 자동 승인하지 않습니다.
출처·본문 근거·자료 품질 검토를 별도 통과해야 합니다.
"""


def run() -> dict[str, Any]:
    """Discover, validate, and write all required label-quality artifacts."""
    # 입력 탐색 → 검사 → Markdown/JSON/CSV 보고서 생성 순서로 실행합니다.
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    candidates = discover_label_workbook(ROOT)
    if not candidates:
        # 라벨 파일이 없으면 가짜 통계를 만들지 않고 명시적인 미실행 결과를 기록합니다.
        result = unavailable_result(
            [ROOT / name for name in ("라벨링.xlsx", "data/라벨링.xlsx")]
        )
        disagreements: list[dict[str, Any]] = []
        review_candidates: list[dict[str, Any]] = []
    else:
        # 동일한 파일이 여러 개라면 정렬된 첫 후보를 사용하고 경로를 보고서에 남깁니다.
        source = candidates[0]
        result = analyze_label_rows(read_xlsx_rows(source), source)
        disagreements = result.pop("disagreements")
        review_candidates = result.pop("manual_review_candidates")
    # 사람이 읽는 보고서와 기계가 읽는 요약을 동시에 생성합니다.
    (REPORT_DIR / "label_quality_report.md").write_text(
        report_markdown(result), encoding="utf-8"
    )
    (REPORT_DIR / "data_quality_summary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    write_csv(
        REPORT_DIR / "label_disagreements.csv",
        disagreements,
        ["row_number", "document_id", "reviewer_a", "reviewer_b"],
    )
    write_csv(
        REPORT_DIR / "label_review_candidates.csv",
        review_candidates,
        [
            "row_number",
            "document_id",
            "title",
            "review_reason",
            "current_relevance",
            "content",
        ],
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
