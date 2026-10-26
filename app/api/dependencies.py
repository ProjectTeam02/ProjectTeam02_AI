import secrets
from pathlib import Path

from fastapi import Depends, Header, HTTPException

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError
from app.db.postgres import get_session
from app.db.repositories.memory_repository import MemoryRepository
from app.ingestion.bok_terms_loader import BOKTermCatalog
from app.rag.generation.answer_generator import AnswerGenerator
from app.rag.grounding.citation_validator import CitationValidator
from app.rag.llamaindex.llm_factory import LLMFactory
from app.rag.llamaindex.retriever import LlamaIndexRetriever
from app.rag.memory.context_builder import ContextBuilder
from app.rag.memory.history_manager import (
    HistoryManager,
    InMemoryConversationRepository,
)
from app.rag.pipelines.multiturn_rag import MultiTurnRAG
from app.rag.query.query_rewriter import QueryRewriter
from app.rag.retrieval.retriever import Retriever
from app.services.memory_service import MemoryService
from app.services.tutor_service import TutorService

# The legacy public-compatible route is retained for local compatibility only.
# The internal Node.js contract never uses this repository or persists backend
# conversation tables; Node.js supplies history and owns its ERD tables.
_legacy_history_repository = InMemoryConversationRepository()


def settings() -> Settings:
    return get_settings()


def _verify_internal_token(
    x_internal_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
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
    _verify_internal_token(x_internal_api_key, authorization)
    if not x_user_id:
        raise HTTPException(status_code=401, detail="X-User-ID is required")
    return x_user_id


async def require_internal_api(
    x_internal_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    _verify_internal_token(x_internal_api_key, authorization)


async def get_tutor_service() -> TutorService:
    settings_value = get_settings()
    try:
        llm = LLMFactory(settings_value).create()
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
        query_rewriter=QueryRewriter(llm, settings_value.llm_timeout_seconds),
        retriever=Retriever(
            LlamaIndexRetriever(settings=settings_value),
            settings_value.retrieval_top_k,
            exact_matcher=bok_catalog,
            related_term_top_k=settings_value.related_term_top_k,
        ),
        context_builder=ContextBuilder(settings_value.context_max_tokens),
        answer_generator=AnswerGenerator(llm, settings_value),
        citation_validator=CitationValidator(
            settings_value.approved_review_status,
            settings_value.grounding_min_overlap,
        ),
    )
    return TutorService(pipeline)


async def get_memory_service(session=Depends(get_session)) -> MemoryService:
    return MemoryService(MemoryRepository(session))
