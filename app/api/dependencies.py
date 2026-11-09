from collections.abc import AsyncGenerator

from fastapi import Header, HTTPException, status

from app.core.config import Settings, get_settings
from app.question_generation.evidence import (
    JsonlEvidenceProvider,
    JsonlExistingQuestionProvider,
)
from app.question_generation.llm import OpenAICompatibleJsonLLM
from app.question_generation.service import QuestionGenerationService


def settings() -> Settings:
    return get_settings()


async def get_current_user_id() -> AsyncGenerator[str, None]:
    # TODO: replace with JWT validation.
    yield "development-user"


def require_internal_api(
    x_internal_api_key: str | None = Header(default=None),
    authorization: str | None = Header(default=None),
) -> None:
    """Protect AI-only routes from public learner traffic."""
    configured_token = get_settings().internal_api_token
    if not configured_token:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="internal authentication is not configured",
        )
    supplied_token = x_internal_api_key
    if supplied_token is None and authorization:
        scheme, _, token = authorization.partition(" ")
        if scheme.casefold() == "bearer":
            supplied_token = token
    if supplied_token != configured_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="valid internal authentication is required",
        )


def get_question_generation_service() -> QuestionGenerationService:
    current_settings = get_settings()
    return QuestionGenerationService(
        settings=current_settings,
        llm=OpenAICompatibleJsonLLM(current_settings),
        evidence_provider=JsonlEvidenceProvider(
            current_settings.question_evidence_path,
            approval_label_path=current_settings.question_approval_label_path,
        ),
        existing_question_provider=JsonlExistingQuestionProvider(
            current_settings.question_existing_path
        ),
    )
