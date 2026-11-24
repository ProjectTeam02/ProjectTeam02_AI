"""Offline-first execution of the five-model tutor comparison."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Callable

from app.core.config import Settings, get_settings
from app.core.exceptions import (
    ConfigurationError,
    GenerationError,
    GenerationTimeoutError,
    RetrievalError,
)
from app.model_comparison.catalog import MODEL_SPECS, ModelSpec
from app.model_comparison.contracts import ComparisonCase, ComparisonResult
from app.model_comparison.io import JsonlResultStore
from app.model_comparison.openrouter_catalog import OpenRouterModelMetadata
from app.rag.generation.answer_generator import (
    TUTOR_PROMPT_VERSION,
    AnswerGenerator,
)
from app.rag.indexing.llm_factory import LLMFactory
from app.rag.memory.context_builder import ContextBuilder
from app.rag.memory.history_manager import HistoryManager
from app.rag.pipeline import MultiTurnRAG
from app.rag.retrieval.query_rewriter import QueryRewriter
from app.rag.retrieval.retriever import InMemoryRetriever, Retriever

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _MockResponse:
    text: str
    raw: dict


class _MockLLM:
    """Deterministic no-network LLM used by the CLI's default mode."""

    def __init__(self, model_id: str):
        self.model_id = model_id

    async def acomplete(self, prompt: str) -> _MockResponse:
        del prompt
        return _MockResponse(
            text="모의 실행입니다. 실제 모델 호출 없이 공통 튜터 경로를 검증했습니다.",
            raw={
                "usage": {
                    "prompt_tokens": 32,
                    "completion_tokens": 18,
                    "total_tokens": 50,
                }
            },
        )


class EvaluationBudgetExceeded(RuntimeError):
    """The explicit evaluation call or cost budget has been exhausted."""


@dataclass(slots=True)
class ComparisonBudget:
    max_calls: int | None = None
    max_cost_usd: float | None = None
    max_retries: int = 0
    min_interval_seconds: float = 0.0
    calls: int = 0
    estimated_cost_usd: float = 0.0
    _last_call_at: float | None = None

    def reserve_call(self) -> None:
        if self.max_calls is not None and self.calls >= self.max_calls:
            raise EvaluationBudgetExceeded("maximum evaluation calls reached")
        self.calls += 1

    async def wait_for_rate_limit(self) -> None:
        if self._last_call_at is not None:
            elapsed = time.perf_counter() - self._last_call_at
            if elapsed < self.min_interval_seconds:
                await asyncio.sleep(self.min_interval_seconds - elapsed)
        self._last_call_at = time.perf_counter()

    def record_cost(self, cost: float | None) -> None:
        if cost is not None:
            self.estimated_cost_usd += cost

    @property
    def exhausted(self) -> bool:
        return (
            self.max_cost_usd is not None
            and self.estimated_cost_usd >= self.max_cost_usd
        )


class _BudgetedLLM:
    """Apply bounded retries and rate limits around an existing LLM adapter."""

    def __init__(self, inner, budget: ComparisonBudget):
        self.inner = inner
        self.budget = budget
        self.model_id = getattr(inner, "model_id", "unknown")

    async def acomplete(self, prompt: str):
        for attempt in range(self.budget.max_retries + 1):
            await self.budget.wait_for_rate_limit()
            self.budget.reserve_call()
            try:
                return await self.inner.acomplete(prompt)
            except Exception:
                if attempt >= self.budget.max_retries:
                    raise


class ModelComparisonRunner:
    """Run identical Multi-turn RAG inputs against each model in the catalog."""

    def __init__(
        self,
        settings: Settings | None = None,
        model_specs: tuple[ModelSpec, ...] = MODEL_SPECS,
        llm_builder: Callable[..., object] | None = None,
        top_k: int | None = None,
        model_metadata: dict[str, OpenRouterModelMetadata] | None = None,
        budget: ComparisonBudget | None = None,
    ):
        self.settings = settings or get_settings()
        self.model_specs = model_specs
        self.llm_builder = llm_builder
        self.top_k = top_k or self.settings.retrieval_top_k
        self.model_metadata = model_metadata or {}
        self.budget = budget

    async def run(
        self,
        cases: list[ComparisonCase],
        output_path: str,
        *,
        execute: bool = False,
        resume: bool = True,
        max_cases: int | None = None,
        run_label: str | None = None,
    ) -> list[ComparisonResult]:
        """Run the batch sequentially and append each result immediately."""

        selected_cases = cases[:max_cases] if max_cases is not None else cases
        mode = run_label or ("live" if execute else "mock")
        store = JsonlResultStore(output_path)
        results: list[ComparisonResult] = []
        budget = self.budget or ComparisonBudget()
        for spec in self.model_specs:
            metadata = self.model_metadata.get(spec.model_id)
            if execute and metadata is not None and not metadata.available:
                for case in selected_cases:
                    result = _error_result(
                        case,
                        spec,
                        mode,
                        ConfigurationError(metadata.reason or "model unavailable"),
                        metadata,
                    )
                    result.status = "excluded_unavailable_model"
                    store.append(result)
                    results.append(result)
                continue
            try:
                generator = self._build_generator(spec, execute, budget)
            except Exception as exc:
                for case in selected_cases:
                    if resume and store.is_completed(case.case_id, spec.model_id, mode):
                        continue
                    result = _error_result(case, spec, mode, exc, metadata)
                    store.append(result)
                    results.append(result)
                continue
            for case in selected_cases:
                if resume and store.is_completed(case.case_id, spec.model_id, mode):
                    continue
                if execute and budget.exhausted:
                    result = _error_result(
                        case,
                        spec,
                        mode,
                        EvaluationBudgetExceeded("maximum evaluation cost reached"),
                        metadata,
                    )
                    result.status = "blocked_budget"
                    store.append(result)
                    results.append(result)
                    continue
                result = await self._run_case(case, spec, generator, mode)
                budget.record_cost(result.estimated_cost_usd)
                if execute and budget.exhausted:
                    result.status = "blocked_budget"
                store.append(result)
                results.append(result)
        return results

    async def _run_case(
        self,
        case: ComparisonCase,
        spec: ModelSpec,
        generator: AnswerGenerator,
        mode: str,
    ) -> ComparisonResult:
        started = time.perf_counter()
        usage: dict[str, int | None] = {}
        try:
            history_manager = HistoryManager(
                max_messages=self.settings.history_max_messages,
                max_tokens=self.settings.history_max_tokens,
            )
            history, history_from_seq = history_manager.from_external(
                conversation_id=f"comparison:{case.case_id}",
                user_id="comparison",
                messages=case.history,
                stage_id=case.stage_id,
                concept_id=case.concept_id,
            )
            pipeline = MultiTurnRAG(
                history_manager=history_manager,
                query_rewriter=QueryRewriter(),
                retriever=Retriever(
                    InMemoryRetriever(case.corpus),
                    top_k=self.top_k,
                ),
                context_builder=ContextBuilder(
                    max_tokens=self.settings.context_max_tokens
                ),
                answer_generator=generator,
            )
            rag_result = await pipeline.run_external(
                user_id="comparison",
                conversation_id=f"comparison:{case.case_id}",
                message=case.question,
                history=history,
                learning_concept=case.learning_concept,
                incorrect_answer=case.incorrect_answer,
                stage_id=case.stage_id,
                concept_id=case.concept_id,
                concept_codes=case.concept_codes,
                history_from_seq=history_from_seq,
                personalized_context=case.personalized_context,
            )
            usage = _merge_usage(
                generator.last_usage,
                getattr(pipeline.query_rewriter, "last_usage", None),
            )
            latency_ms = _elapsed_ms(started)
            status = (
                "mock"
                if mode == "mock"
                else "smoke_ok"
                if mode in {"smoke", "live_smoke"}
                else "ok"
            )
            if not rag_result.retrieved_documents:
                status = "no_evidence"
            return ComparisonResult(
                case_id=case.case_id,
                model_id=spec.model_id,
                mode=mode,
                status=status,
                latency_ms=latency_ms,
                input_hash=case.fingerprint(),
                prompt_version=TUTOR_PROMPT_VERSION,
                answer=rag_result.answer,
                rewritten_query=rag_result.rewritten_query,
                grounding_status="GROUNDED" if rag_result.grounded else "INSUFFICIENT",
                citations=[
                    {
                        "document_id": item.document_id,
                        "chunk_id": item.chunk_id,
                        "score": item.score,
                    }
                    for item in rag_result.citations
                ],
                usage=usage,
                estimated_cost_usd=_estimate_cost(
                    spec, usage, self.model_metadata.get(spec.model_id)
                ),
                model_metadata=_metadata_dict(self.model_metadata.get(spec.model_id)),
                context_variant=case.context_variant,
            )
        except Exception as exc:
            logger.warning(
                "tutor model comparison case failed",
                extra={
                    "case_id": case.case_id,
                    "model_id": spec.model_id,
                    "error_type": type(exc).__name__,
                },
            )
            return ComparisonResult(
                case_id=case.case_id,
                model_id=spec.model_id,
                mode=mode,
                status="error",
                latency_ms=_elapsed_ms(started),
                input_hash=case.fingerprint(),
                prompt_version=TUTOR_PROMPT_VERSION,
                usage=usage,
                error_type=type(exc).__name__,
                error_code=_error_code(exc),
                provider_status=_provider_status(exc),
                model_metadata=_metadata_dict(self.model_metadata.get(spec.model_id)),
                context_variant=case.context_variant,
            )

    def _build_generator(
        self, spec: ModelSpec, execute: bool, budget: ComparisonBudget
    ) -> AnswerGenerator:
        if not execute:
            return AnswerGenerator(llm=_MockLLM(spec.model_id), settings=self.settings)
        model_settings = self.settings.model_copy(
            update={"llm_model": spec.model_id, "llm_provider": "openrouter"}
        )
        metadata = self.model_metadata.get(spec.model_id)
        supported_parameters = (
            set(metadata.supported_parameters) if metadata is not None else None
        )
        if self.llm_builder is not None:
            try:
                llm = self.llm_builder(spec, model_settings, supported_parameters)
            except TypeError as exc:
                # Keep compatibility with existing two-argument test adapters.
                try:
                    llm = self.llm_builder(spec, model_settings)
                except TypeError:
                    raise exc
        else:
            llm = self._build_live_llm(spec, model_settings, supported_parameters)
        return AnswerGenerator(
            llm=_BudgetedLLM(llm, budget),
            settings=model_settings,
        )

    @staticmethod
    def _build_live_llm(
        spec: ModelSpec,
        settings: Settings,
        supported_parameters: set[str] | None = None,
    ):
        del spec
        return LLMFactory(settings).create(supported_parameters)


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _merge_usage(*usages: dict | None) -> dict[str, int | None]:
    prompt_tokens = 0
    completion_tokens = 0
    reasoning_tokens = 0
    found_prompt = found_completion = found_reasoning = False
    for raw in usages:
        if not raw:
            continue
        prompt = _first_int(raw, "prompt_tokens", "input_tokens")
        completion = _first_int(raw, "completion_tokens", "output_tokens")
        reasoning = _nested_int(raw, "completion_tokens_details", "reasoning_tokens")
        if prompt is not None:
            prompt_tokens += prompt
            found_prompt = True
        if completion is not None:
            completion_tokens += completion
            found_completion = True
        if reasoning is not None:
            reasoning_tokens += reasoning
            found_reasoning = True
    input_value = prompt_tokens if found_prompt else None
    output_value = completion_tokens if found_completion else None
    result: dict[str, int | None] = {
        "input_tokens": input_value,
        "output_tokens": output_value,
        "total_tokens": (
            prompt_tokens + completion_tokens
            if found_prompt and found_completion
            else None
        ),
    }
    if found_reasoning:
        result["reasoning_tokens"] = reasoning_tokens
    return result


def _first_int(payload: dict, *keys: str) -> int | None:
    for key in keys:
        value = payload.get(key)
        if value is not None:
            return int(value)
    return None


def _nested_int(payload: dict, *keys: str) -> int | None:
    value: object = payload
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return int(value) if value is not None else None


def _estimate_cost(
    spec: ModelSpec,
    usage: dict[str, int | None],
    metadata: OpenRouterModelMetadata | None = None,
) -> float | None:
    input_tokens = usage.get("input_tokens")
    output_tokens = usage.get("output_tokens")
    if (
        input_tokens is None
        or output_tokens is None
    ):
        return None
    input_price = (
        metadata.input_price_per_million
        if metadata is not None
        else spec.input_price_per_million
    )
    output_price = (
        metadata.output_price_per_million
        if metadata is not None
        else spec.output_price_per_million
    )
    if input_price is None or output_price is None:
        return None
    return round(
        input_tokens / 1_000_000 * input_price
        + output_tokens / 1_000_000 * output_price,
        8,
    )


def _error_code(exc: Exception) -> str:
    if isinstance(exc, EvaluationBudgetExceeded):
        return "budget_exceeded"
    if isinstance(exc, GenerationTimeoutError):
        return "timeout"
    if isinstance(exc, ConfigurationError):
        return "configuration_error"
    if isinstance(exc, GenerationError):
        return "generation_error"
    if isinstance(exc, RetrievalError):
        return "retrieval_error"
    if isinstance(exc, asyncio.CancelledError):
        return "cancelled"
    return "unexpected_error"


def _error_result(
    case: ComparisonCase,
    spec: ModelSpec,
    mode: str,
    exc: Exception,
    metadata: OpenRouterModelMetadata | None = None,
) -> ComparisonResult:
    return ComparisonResult(
        case_id=case.case_id,
        model_id=spec.model_id,
        mode=mode,
        status="error",
        latency_ms=0,
        input_hash=case.fingerprint(),
        prompt_version=TUTOR_PROMPT_VERSION,
        error_type=type(exc).__name__,
        error_code=_error_code(exc),
        provider_status=_provider_status(exc),
        model_metadata=_metadata_dict(metadata),
        context_variant=case.context_variant,
    )


def _metadata_dict(
    metadata: OpenRouterModelMetadata | None,
) -> dict | None:
    return metadata.as_dict() if metadata is not None else None


def _provider_status(exc: Exception) -> int | None:
    value = getattr(exc, "status_code", None)
    return int(value) if isinstance(value, int) and 100 <= value <= 599 else None
