# 파일 역할: 데이터 분석·검증·생성 작업을 독립적으로 실행하는 CLI 스크립트입니다.
"""Run the offline inflation keyword baseline and prepare gold-label evaluation."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from app.question_generation.dataset import select_c0704_candidates

ROOT = Path(__file__).resolve().parents[1]
RAG_PATH_CANDIDATES = (
    ROOT / "data" / "한국은행" / "bok_terms_2026_rag.jsonl",
    ROOT / "data" / "bok_terms_2026_rag.jsonl",
)
OUTPUT_DIR = ROOT / "reports" / "step2"
GOLD_TEMPLATE_PATH = OUTPUT_DIR / "inflation_gold_label_template.csv"
PREDICTIONS_PATH = OUTPUT_DIR / "inflation_keyword_predictions.csv"
EVALUATION_PATH = OUTPUT_DIR / "keyword_evaluation.json"
VALID_GOLD_LABELS = {"approved", "needs_review", "irrelevant"}


def load_rows() -> list[dict]:
    """Load the current BOK JSONL schema and normalize legacy rows."""
    rag_path = next(
        (path for path in RAG_PATH_CANDIDATES if path.is_file()),
        RAG_PATH_CANDIDATES[0],
    )
    rows: list[dict] = []
    for line in rag_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        raw = json.loads(line)
        if "document_id" in raw:
            rows.append(raw)
            continue

        # 현재 BOK RAG 파일은 id/text/metadata 구조이므로
        # 기존 후보 생성기가 사용하는 공통 필드로 변환합니다.
        metadata = raw.get("metadata") or {}
        text = str(raw.get("text") or "")
        term = str(metadata.get("term") or "")
        definition = text.split("설명:", 1)[-1].strip()
        rows.append(
            {
                "document_id": raw.get("id"),
                "term": term,
                "title": term,
                "definition": definition,
                "content": definition,
                "content_hash": hashlib.sha256(
                    definition.encode("utf-8")
                ).hexdigest(),
                "source_id": "BOK",
                "source_type": "BOK",
                "source_url": metadata.get("source_url"),
                "printed_page": metadata.get("printed_page"),
                "review_status": metadata.get("review_status"),
            }
        )
    return rows


def evidence_sentence(row: dict, matched: list[str]) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    text = str(row.get("definition") or row.get("content") or "")
    text = text.split("정의:", 1)[-1].strip()
    sentences = re.split(r"(?<=[.!?。！？])\s+", text)
    for sentence in sentences:
        if any(keyword.casefold() in sentence.casefold() for keyword in matched):
            return " ".join(sentence.split())[:500]
    return " ".join(text.split())[:500]


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def prediction_rows(source_rows: list[dict]) -> list[dict]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    by_id = {str(row.get("document_id")): row for row in source_rows}
    candidates = select_c0704_candidates(source_rows)
    candidate_by_id = {str(row["document_id"]): row for row in candidates}
    output: list[dict] = []
    for source in source_rows:
        document_id = str(source.get("document_id"))
        candidate = candidate_by_id.get(document_id)
        if candidate is None:
            output.append(
                {
                    "document_id": document_id,
                    "term": source.get("term"),
                    "source_review_status": source.get("review_status"),
                    "content_hash": source.get("content_hash"),
                    "source_url": source.get("source_url"),
                    "printed_page": source.get("printed_page"),
                    "keyword_matched": False,
                    "keyword_label": "EXCLUDE",
                    "keyword_score": 0.0,
                    "matched_keywords": "[]",
                    "evidence_sentence": "",
                    "gold_label": "",
                }
            )
            continue
        matched_text = str(candidate.get("classification_reason") or "")
        matched_text = matched_text.split("matched=", 1)[-1]
        matched = [value for value in matched_text.split(",") if value]
        output.append(
            {
                "document_id": document_id,
                "term": by_id[document_id].get("term"),
                "source_review_status": by_id[document_id].get("review_status"),
                "content_hash": by_id[document_id].get("content_hash"),
                "source_url": by_id[document_id].get("source_url"),
                "printed_page": by_id[document_id].get("printed_page"),
                "keyword_matched": True,
                "keyword_label": candidate.get("classification_label"),
                "keyword_score": candidate.get("relevance_score"),
                "matched_keywords": json.dumps(matched, ensure_ascii=False),
                "evidence_sentence": evidence_sentence(by_id[document_id], matched),
                "gold_label": "",
            }
        )
    return output


def read_gold_labels(path: Path) -> dict[str, str]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if not path.is_file():
        return {}
    labels: dict[str, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            document_id = str(row.get("document_id") or "").strip()
            label = str(row.get("gold_label") or "").strip().casefold()
            if document_id and label in VALID_GOLD_LABELS:
                labels[document_id] = label
    return labels


def read_review_data(path: Path) -> dict[str, dict[str, str]]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if not path.is_file():
        return {}
    preserved: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            document_id = str(row.get("document_id") or "").strip()
            if document_id:
                preserved[document_id] = {
                    field: str(row.get(field) or "")
                    for field in (
                        "gold_label",
                        "reviewer",
                        "reviewed_at",
                        "review_note",
                    )
                }
    return preserved


def metrics(predictions: dict[str, str], gold: dict[str, str]) -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    keys = sorted(gold)
    positive = {"approved"}
    tp = sum(predictions[key] in positive and gold[key] in positive for key in keys)
    fp = sum(predictions[key] in positive and gold[key] not in positive for key in keys)
    fn = sum(predictions[key] not in positive and gold[key] in positive for key in keys)
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    per_class: dict[str, dict[str, float | int]] = {}
    for label in sorted(VALID_GOLD_LABELS):
        class_tp = sum(predictions[key] == label and gold[key] == label for key in keys)
        class_fp = sum(predictions[key] == label and gold[key] != label for key in keys)
        class_fn = sum(predictions[key] != label and gold[key] == label for key in keys)
        class_precision = (
            class_tp / (class_tp + class_fp) if class_tp + class_fp else 0.0
        )
        class_recall = class_tp / (class_tp + class_fn) if class_tp + class_fn else 0.0
        class_f1 = (
            2 * class_precision * class_recall / (class_precision + class_recall)
            if class_precision + class_recall
            else 0.0
        )
        per_class[label] = {
            "tp": class_tp,
            "fp": class_fp,
            "fn": class_fn,
            "precision": class_precision,
            "recall": class_recall,
            "f1": class_f1,
        }
    return {
        "binary_approved": {
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        },
        "per_class": per_class,
        "macro_f1": sum(value["f1"] for value in per_class.values()) / len(per_class),
    }


def run() -> dict:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    source_rows = load_rows()
    predictions = prediction_rows(source_rows)
    preserved = read_review_data(GOLD_TEMPLATE_PATH)
    for row in predictions:
        row.update(preserved.get(row["document_id"], {}))
    fields = list(predictions[0])
    write_csv(PREDICTIONS_PATH, predictions, fields)
    template_fields = [
        "document_id",
        "term",
        "source_review_status",
        "content_hash",
        "source_url",
        "printed_page",
        "keyword_label",
        "keyword_score",
        "matched_keywords",
        "evidence_sentence",
        "gold_label",
        "reviewer",
        "reviewed_at",
        "review_note",
    ]
    write_csv(GOLD_TEMPLATE_PATH, predictions, template_fields)
    gold = read_gold_labels(GOLD_TEMPLATE_PATH)
    predicted_labels = {
        row["document_id"]: (
            "approved"
            if row["keyword_label"] in {"DIRECT", "INDIRECT"}
            else "irrelevant"
        )
        for row in predictions
    }
    label_counts = Counter(row["keyword_label"] for row in predictions)
    candidate_count = sum(row["keyword_matched"] for row in predictions)
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "status": "EVALUATED" if len(gold) == len(source_rows) else "NOT_EVALUATED",
        "method": "keyword-only",
        "rule_version": "keyword-v1",
        "source_record_count": len(source_rows),
        "candidate_count": candidate_count,
        "non_exclude_candidate_count": label_counts.get("DIRECT", 0)
        + label_counts.get("INDIRECT", 0),
        "prediction_label_counts": dict(sorted(label_counts.items())),
        "labeled_count": len(gold),
        "required_gold_count": len(source_rows),
        "predictions_path": str(PREDICTIONS_PATH.relative_to(ROOT)),
        "gold_template_path": str(GOLD_TEMPLATE_PATH.relative_to(ROOT)),
        "llm_calls": 0,
        "db_writes": 0,
        "metrics": metrics(predicted_labels, gold)
        if len(gold) == len(source_rows)
        else None,
        "reason": (
            "Full human gold labels are required; blank or partial labels are "
            "not inferred."
            if len(gold) != len(source_rows)
            else None
        ),
    }
    EVALUATION_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
