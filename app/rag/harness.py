from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from time import perf_counter

from app.core.exceptions import GenerationTimeoutError

logger = logging.getLogger(__name__)


_LATENCY_STAGE_MAP = {
    "query_rewriting": "query_rewrite_ms",
    "retrieval": "retrieval_ms",
    "related_retrieval": "related_retrieval_ms",
    "context": "context_build_ms",
    "answer_generation": "llm_generation_ms",
    "groundedness_validation": "grounding_ms",
}


def aggregate_stage_timings(
    trace: list[dict[str, object]] | None,
) -> dict[str, int]:
    """Summarize safe stage timings without including request content.

    A retry is counted in the stage total because it consumes request budget.
    Missing or blocked stages are omitted instead of being represented as a
    fabricated zero.
    """

    timings: dict[str, int] = {}
    for event in trace or []:
        metric = _LATENCY_STAGE_MAP.get(str(event.get("stage")))
        latency = event.get("latency_ms")
        if not metric or not isinstance(latency, (int, float)):
            continue
        timings[metric] = timings.get(metric, 0) + max(0, round(float(latency)))
    return timings


def aggregate_stage_statuses(
    trace: list[dict[str, object]] | None,
) -> dict[str, str]:
    """Return the last observed status for each measurable stage."""

    statuses: dict[str, str] = {}
    for event in trace or []:
        metric = _LATENCY_STAGE_MAP.get(str(event.get("stage")))
        status = event.get("status")
        if metric and isinstance(status, str):
            statuses[metric] = status
    return statuses


@dataclass(frozen=True, slots=True)
class StageContract:
    name: str
    input_description: str
    output_description: str


@dataclass(frozen=True, slots=True)
class StageEvent:
    stage: str
    status: str
    attempt: int
    latency_ms: int
    error: str | None = None

    def as_dict(self) -> dict[str, object]:
        value: dict[str, object] = {
            "stage": self.stage,
            "status": self.status,
            "attempt": self.attempt,
            "latency_ms": self.latency_ms,
        }
        if self.error:
            value["error"] = self.error
        return value


class ExecutionHarness:
    """Bounded, observable execution wrapper for RAG stages.

    The operation is supplied as a coroutine factory so a retry never reuses a
    cancelled coroutine. No request content or provider secret is logged.
    """

    def __init__(self, timeout_seconds: float = 20.0, max_retries: int = 0):
        self.timeout_seconds = max(0.1, timeout_seconds)
        self.max_retries = max(0, max_retries)

    async def run(
        self,
        contract: StageContract,
        operation,
        trace: list[dict[str, object]],
    ):
        for attempt in range(1, self.max_retries + 2):
            started = perf_counter()
            try:
                value = await asyncio.wait_for(
                    operation(), timeout=self.timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                event = StageEvent(
                    contract.name,
                    "timeout",
                    attempt,
                    round((perf_counter() - started) * 1000),
                    "timeout",
                )
                trace.append(event.as_dict())
                logger.warning("rag stage timed out", extra={"stage": contract.name})
                if attempt <= self.max_retries:
                    continue
                failure = GenerationTimeoutError(f"{contract.name} timed out")
                failure.trace = list(trace)
                raise failure from exc
            except Exception as exc:
                event = StageEvent(
                    contract.name,
                    "error",
                    attempt,
                    round((perf_counter() - started) * 1000),
                    type(exc).__name__,
                )
                trace.append(event.as_dict())
                logger.warning("rag stage failed", extra={"stage": contract.name})
                if attempt <= self.max_retries:
                    continue
                exc.trace = list(trace)
                raise
            event = StageEvent(
                contract.name,
                "ok",
                attempt,
                round((perf_counter() - started) * 1000),
            )
            trace.append(event.as_dict())
            logger.info("rag stage completed", extra={"stage": contract.name})
            return value
        raise RuntimeError(f"stage retry policy exhausted: {contract.name}")
