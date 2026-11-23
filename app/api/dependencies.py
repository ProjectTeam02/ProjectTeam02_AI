# 파일 역할: HTTP API 계층의 의존성 또는 라우터를 정의합니다.
import logging
import secrets
from pathlib import Path

from fastapi import Depends, Header, HTTPException

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError
from app.question_generation.evidence import (
    JsonlEvidenceProvider,
    JsonlExistingQuestionProvider,
)
from app.question_generation.jobs import (
    InMemoryQuestionJobRepository,
    QuestionGenerationJobService,
)
from app.question_generation.llm import OpenAICompatibleJsonLLM
from app.question_generation.service import QuestionGenerationService
from app.rag.generation.answer_generator import AnswerGenerator
from app.rag.generation.fallback_llm import FallbackLLM
from app.rag.grounding.citation_validator import CitationValidator
from app.rag.indexing.llm_factory import LLMFactory
from app.rag.ingestion.bok_terms_loader import BOKTermCatalog
from app.rag.memory.concept_graph import ConceptGraphContextBuilder
from app.rag.memory.context_builder import ContextBuilder
from app.rag.memory.history_manager import (
    HistoryManager,
    InMemoryConversationRepository,
)
from app.rag.pipeline import MultiTurnRAG
from app.rag.retrieval.llamaindex_retriever import LlamaIndexRetriever
from app.rag.retrieval.postgres_sparse import PostgresSparseRetriever
from app.rag.retrieval.query_rewriter import QueryRewriter
from app.rag.retrieval.reranker import LexicalReranker
from app.rag.retrieval.retriever import Retriever
from app.services.tutor_service import TutorService

# The legacy public-compatible route is retained for local compatibility only.
# The internal Node.js contract never uses this repository or persists backend
# conversation tables; Node.js supplies history and owns its ERD tables.
_legacy_history_repository = InMemoryConversationRepository()
_question_job_repository = InMemoryQuestionJobRepository()
logger = logging.getLogger(__name__)


def settings() -> Settings:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return get_settings()


def _verify_internal_token(
    x_internal_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    configured_token = get_settings().internal_api_token
    supplied_token = x_internal_api_key
    if (
        not supplied_token
        and authorization
        and authorization.lower().startswith("bearer ")
    ):
        supplied_token = authorization[7:].strip()
    if (
        not configured_token
        or not supplied_token
        or not secrets.compare_digest(supplied_token, configured_token)
    ):
        raise HTTPException(
            status_code=401, detail="valid internal authentication is required"
        )


async def get_current_user_id(
    x_internal_api_key: str | None = Header(default=None),
    x_user_id: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> str:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    _verify_internal_token(x_internal_api_key, authorization)
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-ID is required")
    return x_user_id


async def require_internal_api(
    x_internal_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    _verify_internal_token(x_internal_api_key, authorization)


async def get_tutor_service() -> TutorService:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    settings_value = get_settings()
    tutor_settings = settings_value.for_tutor()
    try:
        primary_llm = LLMFactory(tutor_settings).create()
        llm = _build_tutor_llm(settings_value, tutor_settings, primary_llm)
    except ConfigurationError as exc:
        # Dependency resolution happens before the route handler's try/except.
        # Convert provider configuration failures into the same safe 503 used
        # for runtime model failures, without exposing a key or secret.
        raise HTTPException(
            status_code=503,
            detail="AI provider configuration is unavailable",
        ) from exc
    bok_catalog = None
    if (
        settings_value.bok_hybrid_search_enabled
        and Path(settings_value.bok_terms_path).is_file()
    ):
        bok_catalog = BOKTermCatalog(
            Path(settings_value.bok_terms_path),
            settings_value.approved_review_status,
        )
    history = HistoryManager(
        _legacy_history_repository,
        max_messages=settings_value.history_max_messages,
        max_tokens=settings_value.history_max_tokens,
    )
    pipeline = MultiTurnRAG(
        history_manager=history,
        query_rewriter=QueryRewriter(llm, tutor_settings.llm_timeout_seconds),
        retriever=Retriever(
            LlamaIndexRetriever(settings=settings_value),
            settings_value.retrieval_top_k,
            exact_matcher=bok_catalog,
            related_term_top_k=settings_value.related_term_top_k,
            sparse_backend=(
                PostgresSparseRetriever(settings_value)
                if settings_value.sparse_retrieval_enabled
                else None
            ),
            reranker=(LexicalReranker() if settings_value.reranking_enabled else None),
            fusion_k=settings_value.retrieval_fusion_k,
        ),
        context_builder=ContextBuilder(
            settings_value.context_max_tokens,
            concept_graph_builder=ConceptGraphContextBuilder(
                max_depth=settings_value.concept_graph_max_depth,
                max_nodes=settings_value.concept_graph_max_nodes,
                max_tokens=settings_value.concept_graph_max_tokens,
            ),
        ),
        answer_generator=AnswerGenerator(llm, tutor_settings),
        citation_validator=CitationValidator(
            settings_value.approved_review_status,
            settings_value.grounding_min_overlap,
        ),
    )
    return TutorService(pipeline)


def get_question_generation_service() -> QuestionGenerationService:
    current_settings = get_settings()
    question_settings = current_settings.for_question_generation()
    return QuestionGenerationService(
        settings=question_settings,
        llm=OpenAICompatibleJsonLLM(question_settings),
        evidence_provider=JsonlEvidenceProvider(
            current_settings.question_evidence_path,
            approval_label_path=current_settings.question_approval_label_path,
        ),
        existing_question_provider=JsonlExistingQuestionProvider(
            current_settings.question_existing_path
        ),
    )


def _build_tutor_llm(settings_value: Settings, tutor_settings: Settings, primary_llm):
    """Add an opt-in fallback while keeping the primary model authoritative."""

    fallback_model = settings_value.tutor_fallback_llm_model
    if (
        not settings_value.tutor_fallback_enabled
        or primary_llm is None
        or not fallback_model
        or fallback_model == tutor_settings.llm_model
    ):
        return primary_llm
    fallback_settings = tutor_settings.model_copy(
        update={
            "llm_provider": (
                settings_value.tutor_fallback_llm_provider
                or tutor_settings.llm_provider
            ),
            "llm_model": fallback_model,
        }
    )
    try:
        fallback_llm = LLMFactory(fallback_settings).create()
    except ConfigurationError as exc:
        logger.warning(
            "tutor_fallback_unavailable",
            extra={
                "fallback_model_id": fallback_settings.llm_model,
                "error_type": type(exc).__name__,
            },
        )
        return primary_llm
    if fallback_llm is None:
        return primary_llm
    return FallbackLLM(
        primary_llm,
        fallback_llm,
        primary_model_id=tutor_settings.llm_model,
        fallback_model_id=fallback_settings.llm_model,
        attempt_timeout_seconds=min(
            tutor_settings.llm_timeout_seconds,
            tutor_settings.internal_request_timeout_seconds / 2,
        ),
    )


def get_question_job_service(
    service: QuestionGenerationService = Depends(get_question_generation_service),
) -> QuestionGenerationJobService:
    """Build the job runner while keeping the idempotency repository singleton."""
    return QuestionGenerationJobService(service, _question_job_repository)
