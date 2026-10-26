"""Evaluate BOK hybrid retrieval against the checked local gold IDs."""

from __future__ import annotations

import argparse
import asyncio
import json
import platform
from pathlib import Path
from time import perf_counter

from app.core.config import get_settings
from app.evaluation.rag_metrics import evaluate_retrieval
from app.ingestion.bok_terms_loader import BOKTermCatalog
from app.rag.llamaindex.retriever import LlamaIndexRetriever
from app.rag.query.query_rewriter import QueryRewriter
from app.rag.retrieval.retriever import Retriever


async def evaluate(question_path: Path) -> dict:
    payload = json.loads(question_path.read_text(encoding="utf-8"))
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ValueError("evaluation file must contain a cases list")
    settings = get_settings()
    policy = Retriever(
        LlamaIndexRetriever(settings=settings),
        top_k=settings.retrieval_top_k,
        exact_matcher=(
            BOKTermCatalog(
                Path(settings.bok_terms_path), settings.approved_review_status
            )
            if settings.bok_hybrid_search_enabled
            else None
        ),
        related_term_top_k=settings.related_term_top_k,
    )
    rewriter = QueryRewriter()
    measured: list[dict] = []
    metric_cases: list[tuple[list[str], set[str]]] = []
    no_evidence_hits = 0
    multi_turn_hits = 0
    multi_turn_cases = 0
    for case in cases:
        question = str(case["question"])
        history = case.get("history") or []
        rewritten = await rewriter.rewrite(question, history)
        started = perf_counter()
        documents = await policy.retrieve(rewritten)
        documents = await policy.retrieve_related(documents)
        latency_ms = (perf_counter() - started) * 1000
        retrieved_ids = list(dict.fromkeys(doc.document_id for doc in documents))
        gold = {str(value) for value in case.get("relevant_document_ids", [])}
        if gold:
            metric_cases.append((retrieved_ids, gold))
        elif not retrieved_ids:
            no_evidence_hits += 1
        if case.get("type") == "multi_turn_context":
            multi_turn_cases += 1
            if gold.issubset(set(retrieved_ids[:5])):
                multi_turn_hits += 1
        measured.append(
            {
                "id": case["id"],
                "rewritten_query": rewritten,
                "retrieved_document_ids": retrieved_ids,
                "relevant_document_ids": sorted(gold),
                "latency_ms": round(latency_ms, 3),
            }
        )
    metrics = evaluate_retrieval(metric_cases, k=5)
    no_evidence_cases = sum(
        not case.get("relevant_document_ids") for case in cases
    )
    latencies = sorted(row["latency_ms"] for row in measured)
    warm_latencies = sorted(row["latency_ms"] for row in measured[1:])
    percentile_index = max(0, int(len(latencies) * 0.95) - 1)
    return {
        "schema_version": "bok-rag-evaluation-result.v1",
        "measurement_scope": "retrieval_only",
        "environment": {
            "python": platform.python_version(),
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "collection": settings.vector_store_collection,
            "top_k": settings.retrieval_top_k,
            "minimum_vector_score": settings.retrieval_min_score,
        },
        "case_count": len(cases),
        "answerable_case_count": len(metric_cases),
        "metrics": {
            "recall_at_5": metrics.recall_at_k,
            "mrr": metrics.mrr,
            "no_evidence_accuracy": (
                no_evidence_hits / no_evidence_cases if no_evidence_cases else None
            ),
            "average_latency_ms": (
                round(sum(latencies) / len(latencies), 3) if latencies else 0.0
            ),
            "cold_start_latency_ms": measured[0]["latency_ms"] if measured else 0.0,
            "warm_average_latency_ms": (
                round(sum(warm_latencies) / len(warm_latencies), 3)
                if warm_latencies
                else 0.0
            ),
            "p95_latency_ms": latencies[percentile_index] if latencies else 0.0,
            "citation_accuracy": None,
            "groundedness": None,
            "multi_turn_context_accuracy": (
                multi_turn_hits / multi_turn_cases if multi_turn_cases else None
            ),
            "input_tokens": None,
            "output_tokens": None,
            "cost": None,
        },
        "unmeasured_reason": (
            "No paid LLM call was made. Citation, groundedness, answer quality, "
            "provider token usage, and cost require a separately authorized full run."
        ),
        "cases": measured,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--questions", type=Path, default=Path("data/bok_eval_questions.json")
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = asyncio.run(evaluate(args.questions))
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
