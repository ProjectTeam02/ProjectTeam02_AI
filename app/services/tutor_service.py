from __future__ import annotations

import asyncio
import time

from app.core.config import get_settings
from app.core.exceptions import (
    ConfigurationError,
    ConversationAccessError,
    GenerationTimeoutError,
)
from app.rag.generation.answer_generator import AnswerGenerator
from app.rag.pipelines.multiturn_rag import MultiTurnRAG
from app.schemas.tutor import (
    Citation,
    GroundingStatus,
    InternalTutorRequest,
    InternalTutorResponse,
    InternalTutorSource,
    InternalTutorUsage,
    TutorRequest,
    TutorResponse,
)


class TutorService:
    def __init__(self, pipeline: MultiTurnRAG | None = None):
        self.pipeline = pipeline or MultiTurnRAG()

    async def answer(
        self, request: TutorRequest, authenticated_user_id: str | None = None
    ) -> TutorResponse:
        if (
            authenticated_user_id is not None
            and request.user_id != authenticated_user_id
        ):
            raise ConversationAccessError(
                "request user_id does not match authenticated user"
            )
        self._ensure_llm_available()
        result = await self.pipeline.run(
            user_id=authenticated_user_id or request.user_id,
            message=request.message,
            conversation_id=request.conversation_id,
            learning_concept=request.learning_concept,
            incorrect_answer=request.incorrect_answer,
        )
        return TutorResponse(
            answer=result.answer,
            conversation_id=result.conversation_id,
            citations=[
                Citation(
                    document_id=item.document_id,
                    chunk_id=item.chunk_id,
                    title=item.title,
                    source=item.source,
                    source_id=item.source_id or item.document_id,
                    url=item.source_url or item.source,
                    version=item.version,
                    score=item.score,
                )
                for item in result.citations
            ],
            grounded=result.grounded,
        )

    async def answer_internal(
        self, request: InternalTutorRequest
    ) -> InternalTutorResponse:
        settings = get_settings()
        generator = self.pipeline.answer_generator
        self._ensure_llm_available()

        learning_context = request.context
        stage_id = (
            str(learning_context.stage_id)
            if learning_context and learning_context.stage_id
            else None
        )
        concept_id = (
            str(learning_context.concept_id)
            if learning_context and learning_context.concept_id
            else None
        )
        concept_code = learning_context.concept_code if learning_context else None
        knowledge_scope = request.knowledge_scope
        history, history_from_seq = self.pipeline.history_manager.from_external(
            conversation_id=str(request.conversation_id),
            user_id=str(request.user_id),
            messages=request.history,
            summary=request.summary,
            summary_until_seq=request.summary_until_seq,
            stage_id=stage_id,
            concept_id=concept_id,
        )

        query_rewriter = self.pipeline.query_rewriter
        query_rewriter.last_usage = None
        started = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self.pipeline.run_external(
                    user_id=str(request.user_id),
                    message=request.question,
                    conversation_id=str(request.conversation_id),
                    history=history,
                    learning_concept=concept_code,
                    stage_id=stage_id,
                    concept_id=concept_id,
                    concept_codes=(
                        knowledge_scope.concept_codes if knowledge_scope else None
                    ),
                    history_from_seq=history_from_seq,
                ),
                timeout=settings.internal_request_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise GenerationTimeoutError("internal tutor request timed out") from exc

        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
        usage = self._usage(
            result=result,
            latency_ms=latency_ms,
            generator=generator,
            query_rewriter=query_rewriter,
            retriever=self.pipeline.retriever,
            settings=settings,
        )
        return InternalTutorResponse(
            requestId=request.request_id,
            answer=result.answer,
            rewrittenQuery=result.rewritten_query,
            groundingStatus=(
                GroundingStatus.GROUNDED
                if result.grounded
                else GroundingStatus.INSUFFICIENT
            ),
            historyFromSeq=result.history_from_seq,
            sources=[
                InternalTutorSource(
                    documentId=item.document_id,
                    documentVersion=item.version,
                    chunkId=item.chunk_id,
                    titleSnapshot=item.title,
                    conceptCode=item.concept_code,
                    rank=rank,
                    relevanceScore=self._safe_score(item.score),
                )
                for rank, item in enumerate(result.citations, start=1)
            ],
            usage=usage,
        )

    @staticmethod
    def _safe_score(score: float | None) -> float | None:
        if score is None:
            return None
        score = float(score)
        return score if 0.0 <= score <= 1.0 else None

    def _ensure_llm_available(self) -> None:
        if isinstance(self.pipeline.answer_generator, AnswerGenerator):
            if self.pipeline.answer_generator.llm is None:
                raise ConfigurationError(
                    "an LLM provider is required for the tutor API"
                )

    @classmethod
    def _usage(
        cls,
        *,
        result,
        latency_ms: int,
        generator,
        query_rewriter,
        retriever,
        settings,
    ) -> InternalTutorUsage:
        raw_usages = [
            getattr(query_rewriter, "last_usage", None),
            getattr(generator, "last_usage", None),
        ]
        input_tokens = cls._sum_usage(raw_usages, "prompt_tokens", "input_tokens")
        output_tokens = cls._sum_usage(raw_usages, "completion_tokens", "output_tokens")
        methods = {item.retrieval_method for item in result.retrieved_documents}
        if not methods:
            retrieval_strategy = "NONE"
        elif {"exact", "vector"}.issubset(methods):
            retrieval_strategy = "HYBRID_EXACT_VECTOR"
        elif "exact" in methods:
            retrieval_strategy = "EXACT"
        else:
            retrieval_strategy = "VECTOR"

        model_id = getattr(generator, "model_id", None)
        if model_id is None and getattr(generator, "llm", None) is not None:
            model_id = settings.llm_model
        backend = getattr(retriever, "backend", None)
        embedding_model_id = None
        if backend is not None and hasattr(backend, "settings"):
            backend_settings = backend.settings
            embedding_model_id = (
                "deterministic-local"
                if backend_settings.embedding_provider == "deterministic"
                else backend_settings.embedding_model
            )

        return InternalTutorUsage(
            modelId=model_id,
            embeddingModelId=embedding_model_id,
            inputTokens=input_tokens,
            outputTokens=output_tokens,
            latencyMs=latency_ms,
            cacheHit=False,
            retrievalStrategy=retrieval_strategy,
            estimatedCost=None,
            currency=None,
        )

    @staticmethod
    def _sum_usage(usages: list[dict | None], *keys: str) -> int | None:
        values: list[int] = []
        for usage in usages:
            if not usage:
                continue
            for key in keys:
                value = usage.get(key) if isinstance(usage, dict) else None
                if value is not None:
                    values.append(int(value))
                    break
        return sum(values) if values else None
