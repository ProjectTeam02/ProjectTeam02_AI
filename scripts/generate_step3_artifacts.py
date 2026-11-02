# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
"""Prepare STEP 3-A review samples and reproducible keyword predictions."""

from __future__ import annotations

import csv
import hashlib
import json
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from scripts.evaluate_inflation_keyword import (
    RAG_PATH_CANDIDATES,
    prediction_rows,
)
from scripts.evaluate_inflation_keyword import (
    load_rows as load_bok_rows,
)
from scripts.generate_step2_design_artifacts import build_candidates

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUTPUT = ROOT / "reports" / "step3"
RAG_PATH = next(
    (path for path in RAG_PATH_CANDIDATES if path.is_file()),
    RAG_PATH_CANDIDATES[0],
)
SEED = 20261029
RANDOM_SAMPLE_SIZE = 100
BOUNDARY_SAMPLE_SIZE = 50
CURRICULUM_PATHS = (
    DATA / "mentor_dataset" / "curriculum_full.json",
    DATA / "curriculum.json",
    DATA / "curriculum" / "curriculum_full.json",
)
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


def load_rows() -> list[dict]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    # BOK JSONL의 현재 중첩 구조와 과거 평탄화 구조를 공통 형태로 읽습니다.
    return load_bok_rows()


def evidence_sentence(row: dict, terms: list[str]) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    text = str(row.get("definition") or row.get("content") or "")
    text = text.split("정의:", 1)[-1].strip()
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    for sentence in sentences:
        if any(term.casefold() in sentence.casefold() for term in terms):
            return " ".join(sentence.split())[:500]
    return " ".join(text.split())[:500]


def boundary_score(row: dict) -> tuple[int, list[str]]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    term_text = " ".join(
        str(row.get(key) or "") for key in ("term", "term_kr", "term_en", "title")
    )
    body_text = " ".join(str(row.get(key) or "") for key in ("definition", "content"))
    matched = [
        keyword
        for keyword in BOUNDARY_TERMS
        if keyword.casefold() in body_text.casefold()
    ]
    score = len(set(matched))
    if any(keyword.casefold() in term_text.casefold() for keyword in BOUNDARY_TERMS):
        score += 5
    return score, sorted(set(matched))


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


def review_row(
    row: dict,
    prediction: dict,
    sample_type: str,
    sample_reason: str,
    candidate: dict | None = None,
    boundary_terms: list[str] | None = None,
) -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    evidence_terms = boundary_terms or [
        value
        for value in str(prediction.get("matched_keywords") or "").split(",")
        if value
    ]
    return {
        "sample_type": sample_type,
        "sample_reason": sample_reason,
        "population": "BOK_RAG_789",
        "pilot_chapter_label": "인플레이션",
        "chapter_id": None,
        "concept_id": None,
        "concept_code": None,
        "stage_id": None,
        "document_id": row.get("document_id"),
        "source_id": row.get("source_id"),
        "term": row.get("term"),
        "content_hash": row.get("content_hash"),
        "source_url": row.get("source_url"),
        "printed_page": row.get("printed_page"),
        "source_review_status": row.get("review_status"),
        "license_value": row.get("license"),
        "license_status": (
            candidate.get("license_status")
            if candidate
            else "pending_permission_attribution_review"
        ),
        "keyword_matched": prediction.get("keyword_matched"),
        "keyword_label": prediction.get("keyword_label"),
        "keyword_score": prediction.get("keyword_score"),
        "matched_keywords": (
            candidate.get("matched_keywords") if candidate else boundary_terms or []
        ),
        "proposed_mapping_class": candidate.get("proposed_mapping_class")
        if candidate
        else "not_selected",
        "evidence_sentence": (
            candidate.get("evidence_sentence")
            if candidate
            else evidence_sentence(row, evidence_terms)
        ),
        "mapping_review_status": "",
        "gold_label": "",
        "reviewer": "",
        "reviewed_at": "",
        "review_note": "",
    }


def build_chunk_design() -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return {
        "status": "DESIGN_ONLY_NO_DB_WRITE",
        "document_to_chunk": {
            "document_id": "one canonical source record and one RAGDocument",
            "chunk_id": (
                "generated after SentenceSplitter; not present in BOK source JSONL"
            ),
            "splitter": "LlamaIndex SentenceSplitter",
            "chunk_size": 700,
            "chunk_overlap": 100,
            "current_chunk_id_rule": "document_id:sha256(content)[:12]:chunk_index",
        },
        "current_storage": {
            "document_table": "rag_documents",
            "chunk_table": "rag_document_chunks",
            "vector_owner": "LlamaIndex PGVectorStore",
            "application_registry_embedding": (
                "RAGChunk.embedding is None; metadata/audit only"
            ),
            "document_content_dedup": "RAGDocument.content_hash unique",
        },
        "proposed_embedding_cache_key": {
            "format": (
                "sha256(provider|model|dimension|document_version|"
                "document_content_hash|chunk_size|chunk_overlap|chunk_id|"
                "chunk_content_hash)"
            ),
            "required_inputs": [
                "embedding_provider",
                "embedding_model",
                "embedding_dimension",
                "document_version",
                "document_content_hash",
                "chunk_size",
                "chunk_overlap",
                "chunk_id",
                "chunk_content_hash",
            ],
            "reason": (
                "Changing model, version, source text, or chunking must invalidate "
                "the cache."
            ),
        },
        "invalidation_rules": [
            "source content_hash changes",
            "document_version changes",
            "chunk_size or chunk_overlap changes",
            "embedding provider/model/dimension changes",
            "chunk text hash changes",
        ],
        "implementation_note": (
            "This is a design proposal only; no schema or index change was made "
            "in STEP 3-A."
        ),
    }


def main() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    OUTPUT.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    predictions = prediction_rows(rows)
    for prediction in predictions:
        prediction["rule_version"] = "keyword-v1"
    write_csv(
        OUTPUT / "keyword_predictions.csv",
        predictions,
        list(predictions[0]),
    )
    by_id = {str(row.get("document_id")): row for row in rows}
    predictions_by_id = {str(row["document_id"]): row for row in predictions}
    candidates = build_candidates(rows)
    candidates_by_id = {str(row["document_id"]): row for row in candidates}
    candidate_ids = set(candidates_by_id)
    non_candidates = [
        row for row in rows if str(row.get("document_id")) not in candidate_ids
    ]
    boundary_ranked = []
    for row in non_candidates:
        score, matched = boundary_score(row)
        boundary_ranked.append((score, str(row.get("document_id")), matched, row))
    boundary_ranked.sort(key=lambda item: (-item[0], item[1]))
    boundary_selected = boundary_ranked[:BOUNDARY_SAMPLE_SIZE]
    boundary_ids = {item[1] for item in boundary_selected}
    random_pool = [
        row for row in non_candidates if str(row.get("document_id")) not in boundary_ids
    ]
    if len(random_pool) < RANDOM_SAMPLE_SIZE:
        raise ValueError(
            "random sample size exceeds remaining non-candidate population"
        )
    random_ids = set(
        random.Random(SEED).sample(
            sorted(str(row.get("document_id")) for row in random_pool),
            RANDOM_SAMPLE_SIZE,
        )
    )
    candidate_review = [
        review_row(
            by_id[document_id],
            predictions_by_id[document_id],
            "candidate_55",
            "selected by existing keyword-v1 baseline",
            candidate=candidates_by_id[document_id],
        )
        for document_id in sorted(candidate_ids)
    ]
    boundary_review = [
        review_row(
            row,
            predictions_by_id[str(row.get("document_id"))],
            "boundary_50",
            "not selected by keyword-v1; ranked by related economic context terms",
            boundary_terms=matched,
        )
        for _, _, matched, row in boundary_selected
    ]
    random_review = [
        review_row(
            by_id[document_id],
            predictions_by_id[document_id],
            "random_100",
            f"not selected by keyword-v1; seeded random sample seed={SEED}",
        )
        for document_id in sorted(random_ids)
    ]
    review_rows = candidate_review + boundary_review + random_review
    review_fields = list(review_rows[0])
    write_csv(OUTPUT / "candidate_review_sheet.csv", candidate_review, review_fields)
    write_csv(OUTPUT / "boundary_review_sheet.csv", boundary_review, review_fields)
    write_csv(OUTPUT / "random_review_sheet.csv", random_review, review_fields)
    write_csv(OUTPUT / "gold_label_template.csv", review_rows, review_fields)
    full_fields = [
        "document_id",
        "term",
        "source_review_status",
        "content_hash",
        "source_url",
        "printed_page",
        "keyword_matched",
        "keyword_label",
        "keyword_score",
        "matched_keywords",
        "evidence_sentence",
        "gold_label",
        "reviewer",
        "reviewed_at",
        "review_note",
    ]
    write_csv(OUTPUT / "full_corpus_gold_template.csv", predictions, full_fields)
    sample_id_digest = hashlib.sha256(
        "\n".join(sorted(str(row["document_id"]) for row in review_rows)).encode()
    ).hexdigest()
    manifest = {
        "status": "READY_FOR_HUMAN_REVIEW",
        "source": str(RAG_PATH.relative_to(ROOT)),
        "source_sha256": hashlib.sha256(RAG_PATH.read_bytes()).hexdigest(),
        "population_count": len(rows),
        "keyword_selected_count": len(candidate_ids),
        "keyword_not_selected_count": len(non_candidates),
        "boundary_sample_count": len(boundary_review),
        "random_sample_count": len(random_review),
        "combined_review_count": len(review_rows),
        "random_seed": SEED,
        "random_method": (
            "random.Random(seed).sample(sorted(remaining_document_ids), 100)"
        ),
        "boundary_method": (
            "top 50 non-selected rows ranked by related economic context term score, "
            "then document_id"
        ),
        "boundary_terms": list(BOUNDARY_TERMS),
        "review_document_id_sha256": sample_id_digest,
        "general_population_recall_allowed": False,
        "notes": [
            "Gold labels are blank and must be entered by a human reviewer.",
            (
                "needs_review is deferred in binary relevance metrics, not treated "
                "as negative."
            ),
            "A sampled result is not an exact recall estimate for all 789 documents.",
        ],
    }
    (OUTPUT / "sampling_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "STEP3A_REVIEW_DATA_READY",
        "source_record_count": len(rows),
        "source_sha256": hashlib.sha256(RAG_PATH.read_bytes()).hexdigest(),
        "source_review_status_counts": dict(
            sorted(Counter(str(row.get("review_status")) for row in rows).items())
        ),
        "keyword_prediction_counts": dict(
            sorted(Counter(str(row["keyword_label"]) for row in predictions).items())
        ),
        "review_counts": {
            "candidate_55": len(candidate_review),
            "boundary_50": len(boundary_review),
            "random_100": len(random_review),
            "combined": len(review_rows),
        },
        "gold_label_counts": {"approved": 0, "needs_review": 0, "irrelevant": 0},
        "gold_evaluation_status": "NOT_EVALUATED",
        "curriculum": {
            "paths_checked": [str(path) for path in CURRICULUM_PATHS],
            "canonical_file_found": any(path.is_file() for path in CURRICULUM_PATHS),
            "design_doc_found": (
                ROOT / "docs" / "CURRICULUM_MAPPING_DESIGN.md"
            ).is_file(),
            "design_reference_ids": ["C0704", "R07_S04", "C0701", "C0703"],
            "production_ids_confirmed": False,
        },
        "enum_audit": {
            "source_review_status": ["approved", "needs_review"],
            "mapping_review_status_proposed": [
                "approved",
                "needs_review",
                "irrelevant",
            ],
            "existing_keyword_classification_labels": ["DIRECT", "INDIRECT", "EXCLUDE"],
            "existing_candidate_review_status": "PENDING",
            "conflict": (
                "PENDING and DIRECT/INDIRECT/EXCLUDE are model/workflow outputs, "
                "not the same as Gold Label enums."
            ),
        },
        "chunk_embedding_design": "reports/step3/chunk_embedding_design.json",
        "llm_calls": 0,
        "db_writes": 0,
        "source_data_modified": False,
    }
    (OUTPUT / "chunk_embedding_design.json").write_text(
        json.dumps(build_chunk_design(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (OUTPUT / "step3_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
