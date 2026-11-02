# 파일 역할: 실제 데이터 파일의 메타데이터 필드 보유 여부를 점검합니다.
# ruff: noqa: E501
"""Audit keyword/root_topic/relation_type/summary against available artifacts."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from _pipeline_support import write_json

# 모든 입력·출력 경로를 저장소 루트 기준으로 고정합니다.
ROOT = Path(__file__).resolve().parents[1]
# FIELD_GROUPS는 반드시 존재해야 하는 정식 필드만 검사합니다.
FIELD_GROUPS = {
    "keyword": ("keyword",),
    "root_topic": ("root_topic", "rootTopic"),
    "relation_type": ("relation_type", "relationType"),
    "summary": ("summary",),
}
# 기존 데이터의 title/content는 정식 필드가 아니므로 별도 참고 정보로만 표시합니다.
LEGACY_ALIASES = {
    "keyword": ("term", "title"),
    "summary": ("definition", "content", "text"),
}
# 현재 저장소에서 실제로 발견될 수 있는 처리 산출물만 감사 대상으로 지정합니다.
SOURCE_CANDIDATES = (
    ROOT / "data" / "processed" / "normalized_documents.jsonl",
    ROOT / "data" / "processed" / "chunks.jsonl",
    ROOT / "reports" / "step3" / "keyword_predictions.csv",
)


def read_rows(path: Path) -> list[dict[str, Any]]:
    """Read only supported JSONL/CSV audit inputs."""
    # JSON/JSONL과 CSV만 읽고, 원본 파일에는 쓰지 않습니다.
    if path.suffix == ".jsonl":
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def audit_file(path: Path) -> dict[str, Any]:
    """Return field coverage without inferring missing metadata."""
    # 열이 없으면 자동 생성하지 않고 0%로 기록해 실제 부재를 보존합니다.
    rows = read_rows(path)
    available = set().union(*(row.keys() for row in rows)) if rows else set()
    coverage: dict[str, dict[str, Any]] = {}
    for field, aliases in FIELD_GROUPS.items():
        matches = [alias for alias in aliases if alias in available]
        populated = (
            sum(bool(str(row.get(matches[0], "")).strip()) for row in rows)
            if matches
            else 0
        )
        coverage[field] = {
            "source_columns": matches,
            "populated_count": populated,
            "coverage_rate": populated / len(rows) if rows else None,
        }
    return {
        "path": str(path),
        "row_count": len(rows),
        "coverage": coverage,
        "legacy_alias_columns": {
            field: [alias for alias in aliases if alias in available]
            for field, aliases in LEGACY_ALIASES.items()
        },
    }


def metadata_schema() -> dict[str, Any]:
    """Return the proposed schema; this is not a claim about current rows."""
    # 이 함수의 결과는 현재 데이터가 아니라 향후 저장 구조에 대한 제안입니다.
    return {
        "schema_status": "PROPOSAL_ONLY_UNTIL_HUMAN_REVIEW",
        "concept": {
            "concept_id": "string|required|stable concept identifier",
            "keyword": "string|required|official source term",
            "aliases": "array[string]|nullable|source-backed or review-pending aliases",
            "root_topic": "string|nullable|temporary economic domain until curriculum is canonical",
            "relation_type": "array[enum]|nullable|metric,policy,variant,impact,driver,counter,general",
            "base_concept_id": "string|nullable|required when relation_type needs a base concept",
            "summary": "string|nullable|source-grounded concise definition",
            "source_id": "string|required",
            "source_url": "string|nullable",
            "source_locator": "string|nullable",
            "content_hash": "string|required|sha256 of source text",
        },
        "chapter_mapping": {
            "concept_id_or_chunk_id": "string|required",
            "chapter_id": "string|required|must come from canonical curriculum",
            "relevance_score": "number 0..1|LLM judgement, not probability",
            "relevance_band": "enum:0,1,2|human-approved band",
            "matched_keywords": "array[string]",
            "evidence_text": "string|nullable|verbatim source evidence",
            "reasoning": "string|nullable",
            "confidence": "number 0..1|model self-report, not accuracy",
            "review_status": "enum:PENDING,APPROVED,REJECTED,NEEDS_REVISION",
            "classifier_version": "string|nullable",
        },
        "usage_policy": {
            "tutor_allowed": "boolean|derived after source and mapping gates",
            "question_generation_allowed": "boolean|requires relevance 2 and human approval",
        },
        "non_invention_rules": [
            "Do not create aliases that are not in the source without review status.",
            "Do not treat root_topic as chapter_id.",
            "Do not use keyword counts as final relevance.",
            "Do not treat model confidence as measured precision.",
        ],
    }


def chapter_config() -> dict[str, Any]:
    """Return a JSON-readable copy of the draft inflation experiment config."""
    # production curriculum이 없으므로 DRAFT_NOT_CANONICAL 상태를 명시합니다.
    return {
        "config_version": "draft-2026-11-01",
        "curriculum_status": "DRAFT_NOT_CANONICAL",
        "chapter_id": "inflation",
        "chapter_name": "물가와 인플레이션",
        "chapter_description": "물가의 측정·원인·영향·정책을 다루는 실험용 챕터 범위",
        "subtopics": [
            "인플레이션의 개념",
            "물가 측정 지표",
            "인플레이션의 원인",
            "인플레이션의 영향",
            "인플레이션 대응 정책",
            "디플레이션 및 디스인플레이션 비교",
        ],
        "keyword_expansions": {
            "core": [
                "인플레이션",
                "물가 상승",
                "물가상승",
                "소비자물가지수",
                "CPI",
            ],
            "aliases": ["inflation", "Consumer Price Index", "PPI"],
            "related": [
                "생산자물가지수",
                "근원물가",
                "구매력",
                "기대 인플레이션",
                "통화량",
                "기준금리",
                "실질금리",
            ],
            "opposite": ["디플레이션", "디스인플레이션"],
        },
        "inclusion_rules": "본문이 개념·측정·원인·영향·대응 정책을 설명할 때 후보로 포함",
        "exclusion_rules": "단순 언급, 고유명사·법률명, 물가와 무관한 사례의 우연한 등장",
        "rubric_version": "inflation-rubric-draft-v1",
    }


def run() -> dict[str, Any]:
    """Write the audit, proposed schemas, and chapter configuration."""
    # 실제 필드 감사와 설계 파일 생성을 한 번에 수행하는 CLI 진입점입니다.
    existing = [audit_file(path) for path in SOURCE_CANDIDATES if path.is_file()]
    # 한 파일 안에 네 개 정식 필드가 모두 있어야 완전한 메타데이터 원천으로 봅니다.
    all_fields_present = any(
        all(file["coverage"][field]["source_columns"] for field in FIELD_GROUPS)
        for file in existing
    )
    result = {
        "status": (
            "EXECUTED_WITH_AVAILABLE_ARTIFACTS"
            if existing
            else "NO_CANONICAL_METADATA_SOURCE"
        ),
        "source_files": existing,
        "required_field_audit": FIELD_GROUPS,
        "conclusion": (
            "모든 필드가 존재하는 원천 메타데이터 파일을 확인했습니다."
            if all_fields_present
            else "현재 파일에서는 keyword/root_topic/relation_type/summary의 완전한 원천 메타데이터 세트를 확인하지 못했습니다."
        ),
    }
    report_dir = ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    # 감사 결과와 제안 스키마를 서로 다른 파일로 저장해 사실과 설계를 구분합니다.
    write_json(report_dir / "data_quality_summary_metadata.json", result)
    write_json(report_dir / "metadata_schema.json", metadata_schema())
    write_json(report_dir / "chapter_config.json", chapter_config())
    # Markdown 보고서는 교수·멘토가 코드나 JSON을 직접 열지 않아도 읽을 수 있게 합니다.
    lines = [
        "# 경제 용어 메타데이터 구조 감사",
        "",
        f"- 실행 상태: `{result['status']}`",
        "- 본 문서는 현재 보유 파일의 필드 존재 여부와 개선 설계를 구분합니다.",
        "",
        "## 실제 파일 감사",
        "",
    ]
    if not existing:
        lines.append(
            "현재 감사 대상 원천 산출물이 없어 실데이터 필드 검증을 수행하지 못했습니다."
        )
    for file in existing:
        lines.extend([f"### `{file['path']}` ({file['row_count']}건)", ""])
        for field, coverage in file["coverage"].items():
            lines.append(
                f"- `{field}`: 열 `{coverage['source_columns']}`, 채움 `{coverage['populated_count']}건`, 비율 `{coverage['coverage_rate']}`"
            )
        lines.append("")
    lines += [
        "## 유지할 요소",
        "",
        "`keyword`, `root_topic`, `relation_type`, `summary`는 원문 기반 개념 메타데이터로 유지합니다. 다만 챕터 관련도는 별도 매핑 테이블로 분리합니다.",
        "",
        "## 개선할 요소",
        "",
        "- `aliases`와 정규화 표기를 공식 표제어와 분리합니다.",
        "- `root_topic`과 학습 `chapter_id`를 혼동하지 않습니다.",
        "- 다중 관계가 가능한 `relation_type`과 `base_concept_id`를 지원합니다.",
        "- `summary`의 원문 근거와 검수 상태를 추적합니다.",
        "- 키워드 매칭 결과는 후보 신호일 뿐, 관련도·정밀도·확률로 해석하지 않습니다.",
        "",
        "## 생성된 설계 파일",
        "",
        "- `reports/metadata_schema.json`",
        "- `reports/chapter_config.json`",
        "",
        "인플레이션 챕터는 현재 `DRAFT_NOT_CANONICAL` 상태이며 멘토·교수 확정 전까지 최종 기준으로 사용하지 않습니다.",
    ]
    (report_dir / "taxonomy_audit.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
