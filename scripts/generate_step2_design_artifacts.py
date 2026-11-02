# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
# ruff: noqa: E501

"""Generate STEP 2 design artifacts without changing source data or calling APIs."""

from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.question_generation.dataset import select_c0704_candidates
from scripts.evaluate_inflation_keyword import (
    RAG_PATH_CANDIDATES,
)
from scripts.evaluate_inflation_keyword import (
    load_rows as load_bok_rows,
)

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "step2"
RAG_PATH = next(
    (path for path in RAG_PATH_CANDIDATES if path.is_file()),
    RAG_PATH_CANDIDATES[0],
)

CORE_TERMS = {
    "인플레이션",
    "디스인플레이션",
    "디플레이션",
    "스태그플레이션",
    "기대인플레이션",
    "근원인플레이션율",
    "비용인상 인플레이션",
    "수요견인 인플레이션",
    "애그플레이션",
}
MEASUREMENT_POLICY_TERMS = {
    "경직적 물가지수",
    "물가안정목표제",
    "물가지수",
    "소비자물가지수(CPI)",
    "통화정책",
    "통화정책 파급경로",
    "통화정책 운영체제 (Monetary Policy Regime)",
    "통화정책체계 (Monetary Policy Framework)",
    "통화지표",
    "피셔효과",
    "테일러 준칙(Taylor’s Rule)",
    "GDP갭",
    "명목금리/실질금리",
    "실질임금",
    "실질구매력",
    "명목소득/실질소득",
    "실업률갭",
    "자연실업률",
}
EXPLICIT_EXCLUDE_TERMS = {"인플레이션감축법(IRA)"}


def load_rows() -> list[dict]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    # BOK JSONL의 현재 중첩 구조와 과거 평탄화 구조를 공통 형태로 읽습니다.
    return load_bok_rows()


def first_evidence_sentence(row: dict, matched: list[str]) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    text = str(row.get("definition") or row.get("content") or "")
    text = text.split("정의:", 1)[-1].strip()
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    for sentence in sentences:
        if any(keyword.casefold() in sentence.casefold() for keyword in matched):
            return " ".join(sentence.split())[:500]
    return " ".join(text.split())[:500]


def pilot_class(term: str, keyword_label: str) -> tuple[str, str]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if term in EXPLICIT_EXCLUDE_TERMS:
        return (
            "exclude",
            "법률명에 포함된 문자열 오탐 가능성; 인플레이션 개념 정의로 사용하지 않음",
        )
    if term in CORE_TERMS:
        return "core", "인플레이션·물가상승의 직접 개념 또는 대표적인 변형/원인"
    if term in MEASUREMENT_POLICY_TERMS:
        return "related", "물가 측정·통화정책·전파경로를 통해 인플레이션 학습을 보조"
    if keyword_label == "INDIRECT":
        return "context", "관련 표현은 있으나 인플레이션 핵심 개념으로 확정하지 않음"
    return "review", "keyword baseline이 직접으로 표시했지만 사람의 근거 검토가 필요"


def license_status(value: str | None) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return "unknown"
    if "review" in normalized or "permission" in normalized:
        return "pending_permission_attribution_review"
    if normalized in {"approved", "cleared", "verified"}:
        return "approved"
    if normalized in {"rejected", "blocked"}:
        return "rejected"
    return "unverified"


def proposed_usage(mapping_class: str, source_review: str) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if source_review != "approved":
        return "review_only"
    if mapping_class == "exclude":
        return "excluded_for_inflation_pilot"
    if mapping_class == "core":
        return "both_candidate"
    if mapping_class in {"related", "context"}:
        return "tutor_candidate"
    return "review_only"


def build_candidates(rows: list[dict]) -> list[dict]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    by_id = {str(row.get("document_id")): row for row in rows}
    baseline = select_c0704_candidates(rows)
    output: list[dict] = []
    for item in baseline:
        document_id = str(item.get("document_id"))
        source = by_id[document_id]
        mapping_class, mapping_reason = pilot_class(
            str(item.get("term") or ""), str(item.get("classification_label") or "")
        )
        matched = str(item.get("classification_reason") or "").split("matched=", 1)[-1]
        matched_keywords = [value for value in matched.split(",") if value]
        source_review = str(source.get("review_status") or "")
        output.append(
            {
                "pilot_chapter_label": "인플레이션",
                "pilot_chapter_id": None,
                "concept_id": None,
                "concept_code": None,
                "stage_id": None,
                "mapping_status": "PENDING_HUMAN_REVIEW",
                "document_id": document_id,
                "source_id": source.get("source_id"),
                "term": source.get("term"),
                "title": source.get("title"),
                "content_hash": source.get("content_hash"),
                "source_url": source.get("source_url"),
                "printed_page": source.get("printed_page"),
                "source_review_status": source_review,
                "license_value": source.get("license"),
                "license_status": license_status(source.get("license")),
                "keyword_baseline_label": item.get("classification_label"),
                "keyword_baseline_score": item.get("relevance_score"),
                "matched_keywords": matched_keywords,
                "proposed_mapping_class": mapping_class,
                "proposed_usage_type": proposed_usage(mapping_class, source_review),
                "mapping_reason": mapping_reason,
                "evidence_sentence": first_evidence_sentence(source, matched_keywords),
                "evidence_source": "definition/content",
                "review_status": "PENDING_HUMAN_REVIEW",
                "reviewer": None,
                "reviewed_at": None,
                "gold_label": None,
                "review_note": None,
            }
        )
    return output


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    field: (
                        json.dumps(row[field], ensure_ascii=False)
                        if isinstance(row.get(field), (list, dict))
                        else row.get(field)
                    )
                    for field in fields
                }
            )


def build_policy() -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return {
        "design_status": "PROPOSAL_ONLY",
        "physical_storage_policy": {
            "canonical_source": "data/bok_terms_2026_rag.jsonl",
            "deduplication_key": ["source_id", "document_id", "content_hash"],
            "purpose_metadata_storage": "sidecar mapping keyed by document_id + content_hash",
            "physical_duplicate_allowed": False,
            "embedding_policy": "one embedding per unique content_hash; purpose filters are metadata filters",
        },
        "usage_type_enum": [
            "both_candidate",
            "tutor_candidate",
            "question_candidate",
            "review_only",
            "excluded_for_inflation_pilot",
        ],
        "operational_gate": [
            "source_review_status == approved",
            "mapping_review_status == approved",
            "license_status == approved",
            "usage_type allows the requested consumer",
        ],
        "tutor_policy": {
            "approved_data": "candidate only until license is cleared",
            "retrieval_filter": "review_status=approved and license_status=approved",
            "chapter_filter": "concept_id/concept_code/stage_id when canonical curriculum is available",
            "citation_required": True,
        },
        "question_generation_policy": {
            "approved_data": "candidate only until mapping and license are approved",
            "required_metadata": [
                "concept_id",
                "concept_code",
                "stage_id",
                "learning_goal",
                "difficulty",
                "evidence_document_id",
                "evidence_quote",
            ],
            "human_review_required": True,
            "duplicate_question_check_required": True,
        },
        "status_semantics": {
            "source_review_status": {
                "approved": "source passed existing ingestion/index eligibility; not expert or license approval",
                "needs_review": "source has unresolved extraction/review flags; do not index or generate from it",
            },
            "mapping_review_status": {
                "approved": "human reviewer confirms relevance to the named chapter/concept and evidence span",
                "needs_review": "candidate is plausible but evidence, scope, or category is unresolved",
                "irrelevant": "not relevant to the named chapter/concept; retain in canonical source but exclude from that purpose mapping",
            },
            "license_status": {
                "approved": "permission/attribution terms verified for the intended use",
                "pending_review": "license value exists but permission/attribution is not cleared",
                "unknown": "no reliable license evidence",
                "rejected": "use is not allowed",
            },
        },
    }


def build_schema() -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return {
        "design_status": "PROPOSAL_ONLY",
        "identity_fields": {
            "document_id": "string|required|stable source document identifier",
            "source_id": "string|required|source collection identifier",
            "content_hash": "string|required|sha256(content), used for deduplication",
            "document_version": "string|required|source version snapshot",
        },
        "provenance_fields": {
            "source_url": "string|required when known",
            "source_type": "enum:BOK,KDI,KOSIS,OpenDART,AI_HUB,LEREN,UNKNOWN",
            "publisher": "string|nullable",
            "printed_page": "integer|nullable",
        },
        "curriculum_fields": {
            "chapter_label": "string|nullable|human-readable label only",
            "concept_id": "string|nullable|must come from canonical curriculum",
            "concept_code": "string|nullable|must come from canonical curriculum",
            "stage_id": "string|nullable|must come from canonical curriculum",
            "mapping_status": "enum:PENDING_HUMAN_REVIEW,APPROVED,NEEDS_REVIEW,IRRELEVANT",
            "mapping_method": "enum:manual,keyword,llm,hybrid|nullable",
            "evidence_sentence": "string|nullable|reviewable source excerpt",
        },
        "usage_fields": {
            "usage_type": "enum:both_candidate,tutor_candidate,question_candidate,review_only,excluded",
            "tutor_allowed": "boolean|derived only after all gates pass",
            "question_generation_allowed": "boolean|derived only after all gates pass",
        },
        "governance_fields": {
            "source_review_status": "enum:approved,needs_review",
            "mapping_review_status": "enum:approved,needs_review,irrelevant",
            "license_status": "enum:approved,pending_review,unknown,rejected",
            "reviewer": "string|nullable",
            "reviewed_at": "datetime|nullable",
            "review_note": "string|nullable",
        },
        "important_non_inventions": [
            "Do not create chapter/concept/stage IDs from the label '인플레이션'.",
            "C0704 and R07_S04 are code/test references only until a canonical curriculum file is supplied.",
            "Do not treat current BOK review_status=approved as license or pedagogical approval.",
        ],
    }


def build_experiment_design() -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return {
        "design_status": "DESIGN_ONLY_NO_LLM_CALL",
        "task": "inflation relevance classification",
        "input_unit": "one canonical source document row; no duplicated purpose corpus",
        "candidate_pool": "all 789 BOK RAG rows for recall measurement; approved and needs_review reported separately",
        "labels": ["approved", "needs_review", "irrelevant"],
        "gold_label_definition": {
            "approved": "human confirms the document materially teaches the target chapter/concept and evidence is sufficient",
            "needs_review": "human cannot decide without additional context, source verification, or curriculum mapping",
            "irrelevant": "document is not materially relevant to the target chapter/concept; incidental keyword is insufficient",
        },
        "classification_methods": {
            "keyword_only": {
                "input": "normalized term/title/definition/content plus versioned keyword and exclusion lists",
                "output": "label, matched_keywords, score, rule_version, evidence_sentence",
                "current_reference": "app/question_generation/dataset.py::select_c0704_candidates and KeywordRelevanceClassifier",
                "known_limitation": "current baseline marks many incidental mentions as DIRECT; it is a candidate generator, not ground truth",
            },
            "llm_only": {
                "input": "same source row plus chapter learning goal and output schema",
                "output": "label, confidence, rationale, evidence_quote, document_id, model_version",
                "execution_in_step2": "NOT_RUN; no external LLM call",
                "required_guard": "JSON schema validation, evidence quote must be contained in source content, retry/abstain on invalid output",
            },
            "hybrid": {
                "input": "keyword candidates and exclusions followed by LLM review of ambiguous rows",
                "output": "final candidate label, method_trace, evidence, confidence, reviewer_status",
                "recommended_order": [
                    "high-precision exact term and exclusion rules",
                    "LLM only for ambiguous/context candidates",
                    "human review for all approved mappings before operational use",
                ],
            },
        },
        "evaluation": {
            "unit": "document_id, grouped by source_id and chapter mapping",
            "positive_labels": ["approved"],
            "primary_metrics": ["precision", "recall", "f1"],
            "secondary_metrics": [
                "coverage",
                "abstention_rate",
                "false_positive_rate",
                "evidence_span_accuracy",
            ],
            "formula": {
                "precision": "TP / (TP + FP)",
                "recall": "TP / (TP + FN)",
                "f1": "2 * precision * recall / (precision + recall)",
            },
            "split_policy": "human-labeled stratified train/dev/test; do not leak duplicate content_hash across splits",
            "threshold_policy": "choose approval threshold on dev set; report test metrics and confidence intervals",
            "missing_gold_behavior": "NOT_EVALUATED; candidate labels must never be treated as gold",
        },
        "minimum_gold_set": {
            "recommendation": "label all pilot candidates before comparing methods",
            "stratification": [
                "core",
                "related",
                "context",
                "keyword_false_positive",
                "needs_review_source",
            ],
            "double_review": "at least two reviewers for disagreements and a documented adjudication decision",
        },
    }


def main() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    candidates = build_candidates(rows)
    write_csv(
        OUTPUT / "inflation_mapping_candidates.csv",
        candidates,
        list(candidates[0]),
    )
    review_fields = [
        "pilot_chapter_label",
        "pilot_chapter_id",
        "concept_id",
        "concept_code",
        "stage_id",
        "document_id",
        "source_id",
        "term",
        "content_hash",
        "source_url",
        "printed_page",
        "source_review_status",
        "license_value",
        "license_status",
        "keyword_baseline_label",
        "keyword_baseline_score",
        "matched_keywords",
        "proposed_mapping_class",
        "evidence_sentence",
        "mapping_status",
        "gold_label",
        "reviewer",
        "reviewed_at",
        "review_note",
    ]
    write_csv(OUTPUT / "inflation_review_sheet.csv", candidates, review_fields)
    (OUTPUT / "data_usage_policy.json").write_text(
        json.dumps(build_policy(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "metadata_schema.json").write_text(
        json.dumps(build_schema(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "classification_experiment_design.json").write_text(
        json.dumps(build_experiment_design(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "STEP2_DESIGN_COMPLETE",
        "source": str(RAG_PATH.relative_to(ROOT)),
        "source_record_count": len(rows),
        "source_review_status_counts": dict(
            sorted(Counter(str(row.get("review_status")) for row in rows).items())
        ),
        "keyword_baseline_candidate_count": len(candidates),
        "keyword_baseline_labels": dict(
            sorted(
                Counter(
                    str(row["keyword_baseline_label"]) for row in candidates
                ).items()
            )
        ),
        "proposed_mapping_classes": dict(
            sorted(
                Counter(
                    str(row["proposed_mapping_class"]) for row in candidates
                ).items()
            )
        ),
        "pilot_identifiers": {
            "pilot_chapter_label": "인플레이션",
            "chapter_id": None,
            "concept_id": None,
            "concept_code": None,
            "stage_id": None,
            "status": "DESIGN_LABEL_ONLY",
        },
        "license_status_counts": dict(
            sorted(Counter(str(row["license_status"]) for row in candidates).items())
        ),
        "llm_calls": 0,
        "db_writes": 0,
        "source_data_modified": False,
    }
    (OUTPUT / "step2_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
