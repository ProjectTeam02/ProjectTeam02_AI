"""Run offline A0-A3 retrieval comparisons without inventing gold labels.

The input is JSONL, never CSV. A case is eligible for retrieval metrics only
when ``gold_status`` is ``REVIEWED`` and ``relevant_chunk_ids`` is non-empty.
The script can still measure local latency and retrieved IDs for unreviewed
cases, but it reports answer quality, faithfulness, and cost as unavailable
without an LLM run and human-reviewed labels.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.evaluation.rag_metrics import evaluate_retrieval  # noqa: E402
from app.rag.retrieval.query_rewriter import QueryRewriter  # noqa: E402
from app.rag.retrieval.reranker import LexicalReranker  # noqa: E402
from app.rag.retrieval.retriever import (  # noqa: E402
    InMemoryRetriever,
    Retriever,
)
from app.rag.retrieval.types import RetrievedDocument  # noqa: E402

ARMS = ("A0", "A1", "A2", "A3")


def _document(raw: dict[str, Any]) -> RetrievedDocument:
    return RetrievedDocument(
        content=str(raw.get("content", "")),
        source=str(raw.get("source", "fixture")),
        document_id=str(raw.get("document_id", raw.get("id", "unknown"))),
        chunk_id=str(raw.get("chunk_id", raw.get("id", "unknown"))),
        title=raw.get("title"),
        review_status=str(raw.get("review_status", "approved")),
    )


def load_cases(path: Path) -> list[dict[str, Any]]:
    cases: list[dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"{path}:{line_no} must contain a JSON object")
            cases.append(row)
    return cases


async def _run_arm(arm: str, case: dict[str, Any]) -> dict[str, Any]:
    documents = [_document(item) for item in case.get("corpus", [])]
    sparse_documents = [
        _document(item) for item in case.get("sparse_corpus", case.get("corpus", []))
    ]
    history = case.get("history", [])
    question = str(case.get("question", ""))
    query = question
    if arm in {"A1", "A2", "A3"}:
        query = await QueryRewriter().rewrite(question, history)

    retriever = Retriever(InMemoryRetriever(documents), top_k=5)
    if arm in {"A2", "A3"}:
        retriever.sparse_backend = InMemoryRetriever(sparse_documents)
    if arm == "A3":
        retriever.reranker = LexicalReranker()

    started = time.perf_counter()
    retrieved = await retriever.retrieve(query)
    latency_ms = round((time.perf_counter() - started) * 1000, 3)
    expected_terms = [str(item) for item in case.get("expected_context_terms", [])]
    context_accuracy = (
        None
        if not expected_terms
        else all(term.casefold() in query.casefold() for term in expected_terms)
    )
    return {
        "retrieved_ids": [item.chunk_id for item in retrieved],
        "rewritten_query": query,
        "context_accuracy": context_accuracy,
        "latency_ms": latency_ms,
        "token_usage": None,
        "estimated_cost": None,
    }


async def evaluate(path: Path) -> dict[str, Any]:
    cases = load_cases(path)
    by_arm: dict[str, list[dict[str, Any]]] = {arm: [] for arm in ARMS}
    reviewed_count = 0
    for case in cases:
        reviewed = (
            str(case.get("gold_status", "NOT_REVIEWED")).upper() == "REVIEWED"
            and bool(case.get("relevant_chunk_ids"))
        )
        reviewed_count += int(reviewed)
        for arm in ARMS:
            result = await _run_arm(arm, case)
            result["case_id"] = case.get("case_id")
            if reviewed:
                result["relevant_chunk_ids"] = case["relevant_chunk_ids"]
            by_arm[arm].append(result)

    report: dict[str, Any] = {
        "status": "READY" if reviewed_count else "NOT_READY_NO_REVIEWED_GOLD",
        "dataset": str(path),
        "case_count": len(cases),
        "target_case_count": 80,
        "reviewed_gold_count": reviewed_count,
        "gold_policy": "Only REVIEWED cases are scored; generated labels are not gold.",
        "arms": {},
    }
    for arm, results in by_arm.items():
        metric_cases = [
            (row["retrieved_ids"], set(row["relevant_chunk_ids"]))
            for row in results
            if "relevant_chunk_ids" in row
        ]
        retrieval = evaluate_retrieval(metric_cases, k=5) if metric_cases else None
        context_values = [
            row["context_accuracy"]
            for row in results
            if row["context_accuracy"] is not None
        ]
        report["arms"][arm] = {
            "recall_at_5": retrieval.recall_at_k if retrieval else None,
            "ndcg_at_5": retrieval.ndcg_at_k if retrieval else None,
            "mrr": retrieval.mrr if retrieval else None,
            "multi_turn_context_accuracy": (
                mean(context_values) if context_values else None
            ),
            "p50_latency_ms": _percentile(
                [row["latency_ms"] for row in results], 0.50
            ),
            "p95_latency_ms": _percentile(
                [row["latency_ms"] for row in results], 0.95
            ),
            "answer_accuracy": None,
            "faithfulness": None,
            "hallucination_rate": None,
            "token_usage": None,
            "estimated_cost_per_request": None,
            "note": (
                "Retrieval-only offline arm; answer metrics require the same "
                "configured LLM and reviewed labels."
            ),
        }
    report["generation_arms"] = {
        "B0": "NOT_RUN_NO_LLM",
        "B1": "NOT_RUN_NO_LLM",
        "B2": "NOT_RUN_NO_LLM",
        "B3": "NOT_RUN_NO_LLM",
    }
    return report


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, round((len(ordered) - 1) * fraction)))
    return ordered[index]


def write_template(path: Path, count: int) -> None:
    rows = []
    for index in range(1, count + 1):
        rows.append(
            {
                "case_id": f"MT-{index:03d}",
                "gold_status": "NOT_REVIEWED",
                "turns": [],
                "history": [],
                "question": "",
                "corpus": [],
                "relevant_chunk_ids": [],
                "expected_context_terms": [],
                "answerable": None,
                "gold_answer": None,
                "reviewer_id": None,
            }
        )
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path, nargs="?")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--init-template", type=Path)
    parser.add_argument("--count", type=int, default=80)
    args = parser.parse_args()
    if args.init_template:
        write_template(args.init_template, args.count)
        print(json.dumps({"created": str(args.init_template), "count": args.count}))
        return
    if args.dataset is None:
        parser.error("dataset is required unless --init-template is used")
    report = asyncio.run(evaluate(args.dataset))
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(encoded + "\n", encoding="utf-8")
    print(encoded)


if __name__ == "__main__":
    main()
