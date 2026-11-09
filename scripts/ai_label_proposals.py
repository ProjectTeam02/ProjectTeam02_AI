"""Create AI-only relevance proposals for the independent review queue.

이 스크립트의 결과는 사람이 확정한 Gold가 아닙니다. 원문 템플릿을 읽어
``AI_PROPOSED`` 상태의 별도 JSONL을 만들며, 기존 사람 검수 history에는
절대 기록하지 않습니다. API 키가 없을 때는 원문 기반 오프라인 휴리스틱을
사용하고, ``--execute``를 명시하면 설정된 LLM으로 20건 파일럿을 실행할 수
있습니다.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.config import get_settings  # noqa: E402
from app.dataset_pipeline.gold_review import load_template_rows, normalized_text  # noqa: E402
from app.dataset_pipeline.tokenizer import ExactTokenizer, summarize  # noqa: E402
from app.rag.indexing.llm_factory import LLMFactory  # noqa: E402
from scripts._pipeline_support import load_yaml  # noqa: E402

DEFAULT_KDI = ROOT / "reports/step3/kdi_independent_gold_review_template.csv"
DEFAULT_BOK = ROOT / "reports/step3/bok_independent_gold_review_template.csv"
DEFAULT_OUTPUT = ROOT / "data/labeled/precision/ai_label_proposals.jsonl"
DEFAULT_REVIEW_QUEUE = ROOT / "data/labeled/precision/ai_label_review_queue.csv"
DEFAULT_REPORT = ROOT / "reports/ai_label_proposal_report.json"
DEFAULT_CHAPTERS = ROOT / "configs/chapters.yaml"
MODEL_OFFLINE = "offline-content-rubric-v1"
PROMPT_VERSION = "ai-label-proposal-v1"
LABELS = {"0", "1", "2", "NEEDS_REVIEW"}

DIRECT_TERMS = (
    "인플레이션",
    "물가 상승",
    "물가상승",
    "물가 상승률",
    "물가상승률",
    "물가 수준",
    "물가수준",
    "소비자물가지수",
    "소비자물가",
    "생산자물가지수",
    "생산자물가",
    "근원물가",
    "근원인플레이션",
    "기대인플레이션",
    "기대 인플레이션",
    "디플레이션",
    "디스인플레이션",
    "스태그플레이션",
    "수요견인",
    "수요 견인",
    "비용인상",
    "비용 인상",
    "물가 안정",
    "물가안정",
)
INDIRECT_TERMS = (
    "기준금리",
    "통화량",
    "화폐 가치",
    "화폐가치",
    "구매력",
    "실질금리",
    "실질 금리",
    "환율",
    "금리",
)
EXCLUDED_TERMS = ("인플레이션감축법", "인플레이션 감축법")
EXPLANATORY_TERMS = (
    "말한다",
    "뜻한다",
    "현상",
    "지표",
    "측정",
    "상승률",
    "원인",
    "영향",
    "정책",
    "안정",
    "수요",
    "비용",
    "기대",
    "하락",
)


def _sentences(content: str) -> list[str]:
    """Split text conservatively while retaining exact source sentences."""
    values = [part.strip() for part in re.split(r"(?<=[.!?다요])\s+|\n+", content)]
    return [value for value in values if value]


def _matching_sentences(content: str, terms: tuple[str, ...]) -> list[str]:
    normalized = normalized_text(content)
    return [
        sentence
        for sentence in _sentences(content)
        if any(normalized_text(term) in normalized_text(sentence) for term in terms)
        and normalized_text(sentence) in normalized
    ]


def _first_evidence(content: str) -> str:
    return _sentences(content)[0][:500] if _sentences(content) else ""


def _offline_proposal(row: dict[str, str]) -> dict[str, Any]:
    """Make a conservative, content-aware proposal without claiming LLM output."""
    title = row.get("title", "")
    content = row.get("content", "")
    combined = f"{title} {content}"
    direct_matches = [
        term
        for term in DIRECT_TERMS
        if normalized_text(term) in normalized_text(combined)
    ]
    indirect_matches = [
        term
        for term in INDIRECT_TERMS
        if normalized_text(term) in normalized_text(combined)
    ]
    excluded_matches = [
        term
        for term in EXCLUDED_TERMS
        if normalized_text(term) in normalized_text(combined)
    ]
    explanatory_matches = [
        term
        for term in EXPLANATORY_TERMS
        if normalized_text(term) in normalized_text(combined)
    ]
    direct_evidence = _matching_sentences(content, tuple(direct_matches))
    has_explanation = bool(
        any(
            normalized_text(term) in normalized_text(sentence)
            for sentence in direct_evidence
            for term in EXPLANATORY_TERMS
        )
    )

    if excluded_matches and not direct_evidence:
        label = "0"
        reason = (
            "인플레이션 관련 표기가 경제 개념이 아니라 법률명으로 사용되어 "
            "챕터와 직접 관련이 없습니다."
        )
        evidence = _matching_sentences(content, tuple(excluded_matches)) or [
            _first_evidence(content)
        ]
        confidence = 0.86
        needs_review = False
    elif direct_matches and has_explanation:
        label = "2"
        reason = (
            "본문이 인플레이션·물가·측정지표·원인·영향 또는 대응 정책을 "
            f"직접 설명합니다. 확인된 개념: {', '.join(direct_matches[:4])}."
        )
        evidence = direct_evidence or [_first_evidence(content)]
        confidence = 0.78
        needs_review = len(direct_matches) > 3 or len(content) < 40
    elif direct_matches or indirect_matches:
        label = "1"
        matches = direct_matches or indirect_matches
        reason = (
            "본문에 인플레이션 관련 배경 개념이 보이지만 핵심 챕터 내용을 "
            f"직접 설명하는지 추가 확인이 필요합니다: {', '.join(matches[:4])}."
        )
        evidence = _matching_sentences(content, tuple(matches)) or [
            _first_evidence(content)
        ]
        confidence = 0.58
        needs_review = True
    elif not content.strip() or len(content.strip()) < 20:
        label = "NEEDS_REVIEW"
        reason = "원문이 없거나 너무 짧아 챕터 관련성을 판단할 수 없습니다."
        evidence = [_first_evidence(content)]
        confidence = 0.20
        needs_review = True
    else:
        label = "0"
        reason = (
            "본문에서 인플레이션 챕터의 핵심 개념이나 유의미한 배경 연결을 "
            "확인하지 못했습니다."
        )
        evidence = [_first_evidence(content)]
        confidence = 0.72 if not explanatory_matches else 0.55
        needs_review = bool(explanatory_matches and len(content) < 80)

    evidence_quote = next((value for value in evidence if value), "")
    if label != "NEEDS_REVIEW" and not evidence_quote:
        label = "NEEDS_REVIEW"
        reason = "원문에서 검증 가능한 근거 문장을 추출하지 못했습니다."
        needs_review = True
    return {
        "relevance_label": label,
        "reason": reason,
        "evidence_quote": evidence_quote,
        "confidence": confidence,
        "confidence_is_subjective": True,
        "needs_review": needs_review,
        "matched_direct_terms": direct_matches,
        "matched_indirect_terms": indirect_matches,
        "excluded_terms": excluded_matches,
        "analysis_method": MODEL_OFFLINE,
    }


def _second_pass(row: dict[str, str]) -> dict[str, Any]:
    """Run a stricter second heuristic; it is not independent human review."""
    proposal = _offline_proposal(row)
    direct = proposal["matched_direct_terms"]
    evidence = proposal["evidence_quote"]
    if proposal["relevance_label"] == "2" and (not direct or not evidence):
        return {
            "relevance_label": "NEEDS_REVIEW",
            "reason": "엄격 재검토에서 직접 근거 부족",
            "evidence_quote": evidence,
        }
    if proposal["relevance_label"] == "0" and proposal["matched_indirect_terms"]:
        return {
            "relevance_label": "NEEDS_REVIEW",
            "reason": "엄격 재검토에서 간접 연관 가능성 확인",
            "evidence_quote": evidence,
        }
    return {
        "relevance_label": proposal["relevance_label"],
        "reason": proposal["reason"],
        "evidence_quote": evidence,
    }


def _prompt(row: dict[str, str], chapter: dict[str, Any]) -> str:
    return (
        "당신은 경제교육 데이터 검수자입니다. 제목이 아니라 본문 전체를 읽고 "
        "인플레이션 챕터 관련도를 0, 1, 2, NEEDS_REVIEW 중 하나로 분류하세요. "
        "근거 문장은 반드시 원문에서 그대로 복사하고 JSON만 반환하세요.\n"
        + json.dumps(
            {
                "chapter": chapter,
                "document_id": row.get("document_id"),
                "title": row.get("title"),
                "content": row.get("content"),
                "output": {
                    "relevance_label": "0|1|2|NEEDS_REVIEW",
                    "reason": "string",
                    "evidence_quote": "exact substring of content or empty",
                    "confidence": "0..1 subjective confidence",
                    "needs_review": "boolean",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _parse_llm(value: Any, row: dict[str, str]) -> dict[str, Any]:
    raw = getattr(value, "text", None) or str(value)
    start, end = raw.find("{"), raw.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("LLM response does not contain JSON")
    parsed = json.loads(raw[start : end + 1])
    label = str(parsed.get("relevance_label", ""))
    if label not in LABELS:
        raise ValueError("invalid relevance_label")
    confidence = parsed.get("confidence")
    if (
        isinstance(confidence, bool)
        or not isinstance(confidence, (int, float))
        or not 0 <= confidence <= 1
    ):
        raise ValueError("confidence must be between 0 and 1")
    evidence = str(parsed.get("evidence_quote") or "")
    if label != "NEEDS_REVIEW" and evidence not in row.get("content", ""):
        raise ValueError("evidence_quote is not in original content")
    return {
        "relevance_label": label,
        "reason": str(parsed.get("reason", "")),
        "evidence_quote": evidence,
        "confidence": confidence,
        "confidence_is_subjective": True,
        "needs_review": bool(parsed.get("needs_review", False)),
        "analysis_method": "llm_prompted_content_review",
    }


def _load_chapter(path: Path) -> dict[str, Any]:
    payload = load_yaml(path)
    chapters = payload.get("chapters", [])
    if not chapters:
        raise ValueError(f"챕터 설정이 없습니다: {path}")
    return chapters[0]


def _read_existing(path: Path) -> tuple[list[dict[str, Any]], set[str]]:
    if not path.is_file():
        return [], set()
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows, {str(row.get("document_id")) for row in rows}


def _select_rows(rows: list[dict[str, str]], limit: int | None) -> list[dict[str, str]]:
    """Select a pilot sample across KDI/BOK before processing the remainder."""
    if limit is None or limit >= len(rows):
        return rows
    groups: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(row.get("source", "UNKNOWN"), []).append(row)
    selected: list[dict[str, str]] = []
    while len(selected) < limit and groups:
        for source in sorted(list(groups)):
            if groups[source] and len(selected) < limit:
                selected.append(groups[source].pop(0))
            if not groups[source]:
                groups.pop(source)
    return selected


def _write_report(
    path: Path, rows: list[dict[str, Any]], total: int, llm_calls: int
) -> dict[str, Any]:
    labels = Counter(row.get("relevance_label") for row in rows)
    sources = {
        source: dict(
            Counter(
                row.get("relevance_label")
                for row in rows
                if row.get("source") == source
            )
        )
        for source in sorted({row.get("source", "") for row in rows})
    }
    input_tokens = [
        int(row["input_tokens"]) for row in rows if row.get("input_tokens") is not None
    ]
    output_tokens = [
        int(row["output_tokens"])
        for row in rows
        if row.get("output_tokens") is not None
    ]
    report = {
        "status": "AI_PROPOSALS_ONLY",
        "total_template_documents": total,
        "analyzed_documents": len(rows),
        "unprocessed_documents": max(total - len(rows), 0),
        "label_counts": dict(labels),
        "source_label_counts": sources,
        "needs_review_count": sum(bool(row.get("needs_review")) for row in rows),
        "evidence_validation_pass_count": sum(
            bool(row.get("evidence_valid")) for row in rows
        ),
        "second_pass_disagreement_count": sum(
            bool(row.get("second_pass_disagreement")) for row in rows
        ),
        "reviewer_type": "AI",
        "review_status": "AI_PROPOSED",
        "human_gold_created": False,
        "llm_calls": llm_calls,
        "input_tokens": summarize(input_tokens),
        "output_tokens": summarize(output_tokens),
        "cost": None,
        "cost_reason": (
            "가격표가 확인되지 않았거나 오프라인 분석이라 비용을 산출하지 않음"
        ),
        "requires_human_review": True,
        "metrics_status": "NOT_EVALUATED_NEEDS_INDEPENDENT_GOLD",
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def _write_review_queue(path: Path, rows: list[dict[str, Any]]) -> None:
    import csv

    fields = [
        "document_id",
        "source",
        "title",
        "content",
        "content_hash",
        "chapter_id",
        "dataset_version",
        "split",
        "sampling_bucket",
        "relevance_label",
        "reason",
        "evidence_quote",
        "confidence",
        "needs_review",
        "second_pass_label",
        "second_pass_disagreement",
        "reviewer_type",
        "reviewer_model",
        "review_status",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            {field: row.get(field, "") for field in fields} for row in rows
        )


def run(
    kdi_path: Path = DEFAULT_KDI,
    bok_path: Path = DEFAULT_BOK,
    output_path: Path = DEFAULT_OUTPUT,
    report_path: Path = DEFAULT_REPORT,
    review_queue_path: Path = DEFAULT_REVIEW_QUEUE,
    chapter_path: Path = DEFAULT_CHAPTERS,
    limit: int | None = None,
    resume: bool = True,
    execute: bool = False,
    phase: str = "offline_full",
    max_retries: int = 2,
) -> dict[str, Any]:
    templates = load_template_rows([kdi_path, bok_path])
    chapter = _load_chapter(chapter_path)
    tokenizer = ExactTokenizer("gpt-5.6-sol")
    results, existing_ids = _read_existing(output_path) if resume else ([], set())
    selected = [row for row in templates if row.get("document_id") not in existing_ids]
    selected = _select_rows(selected, limit)
    llm = None
    settings = get_settings()
    call_count = 0
    for row in selected:
        started = time.perf_counter()
        prompt = _prompt(row, chapter)
        proposal: dict[str, Any]
        error: str | None = None
        if execute:
            if llm is None:
                llm = LLMFactory(settings).create()
            for attempt in range(max_retries + 1):
                try:
                    response = llm.complete(prompt)
                    proposal = _parse_llm(response, row)
                    call_count += 1
                    break
                except Exception as exc:  # noqa: BLE001 - preserve failed row
                    error = f"{type(exc).__name__}: {exc}"
                    call_count += 1
                    if attempt >= max_retries:
                        proposal = _offline_proposal(row)
                        proposal["needs_review"] = True
                        proposal["analysis_method"] = "llm_failed_offline_fallback"
        else:
            proposal = _offline_proposal(row)
        second = _second_pass(row)
        evidence_valid = bool(
            proposal["evidence_quote"]
            and normalized_text(proposal["evidence_quote"])
            in normalized_text(row.get("content", ""))
        )
        disagreement = proposal["relevance_label"] != second["relevance_label"]
        results.append(
            {
                "document_id": row.get("document_id", ""),
                "chunk_id": row.get("chunk_id", ""),
                "source": row.get("source", ""),
                "title": row.get("title", ""),
                "content_hash": row.get("content_hash", ""),
                "chapter_id": row.get(
                    "chapter_id", chapter.get("chapter_id", "inflation")
                ),
                "dataset_version": row.get("dataset_version", ""),
                "split": row.get("split", ""),
                "sampling_bucket": row.get("sampling_bucket", ""),
                **proposal,
                "evidence_valid": evidence_valid,
                "second_pass_label": second["relevance_label"],
                "second_pass_reason": second["reason"],
                "second_pass_evidence_quote": second["evidence_quote"],
                "second_pass_disagreement": disagreement,
                "reviewer_type": "AI",
                "reviewer_model": settings.llm_model if execute else MODEL_OFFLINE,
                "review_status": "AI_PROPOSED",
                "prompt_version": PROMPT_VERSION,
                "rubric_version": chapter.get("rubric_version", ""),
                "input_tokens": tokenizer.count(prompt) if execute else None,
                "output_tokens": None,
                "latency_seconds": round(time.perf_counter() - started, 3),
                "llm_call_count": 1 if execute else 0,
                "error": error,
                "classified_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    _write_review_queue(review_queue_path, results)
    report = _write_report(report_path, results, len(templates), call_count)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as handle:
        for row in results:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    report["output_path"] = str(output_path)
    report["review_queue_path"] = str(review_queue_path)
    report["phase"] = phase
    report["processed_this_run"] = len(selected)
    report["existing_rows_reused"] = len(existing_ids)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kdi", type=Path, default=DEFAULT_KDI)
    parser.add_argument("--bok", type=Path, default=DEFAULT_BOK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--review-queue", type=Path, default=DEFAULT_REVIEW_QUEUE)
    parser.add_argument("--chapters", type=Path, default=DEFAULT_CHAPTERS)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument(
        "--execute", action="store_true", help="명시적으로 LLM 호출을 실행합니다."
    )
    parser.add_argument("--phase", default="offline_full")
    parser.add_argument("--max-retries", type=int, default=2)
    args = parser.parse_args()
    print(
        json.dumps(
            run(
                kdi_path=args.kdi,
                bok_path=args.bok,
                output_path=args.output,
                report_path=args.report,
                review_queue_path=args.review_queue,
                chapter_path=args.chapters,
                limit=args.limit,
                resume=not args.no_resume,
                execute=args.execute,
                phase=args.phase,
                max_retries=args.max_retries,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
