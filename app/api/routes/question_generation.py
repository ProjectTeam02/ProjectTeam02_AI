from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_question_generation_service,
    require_internal_api,
)
from app.question_generation.service import QuestionGenerationService
from app.schemas.question_generation import (
    GeneratedQuestionResult,
    GenerationRequest,
)

router = APIRouter(
    prefix="/questions",
    tags=["question-generation"],
    dependencies=[Depends(require_internal_api)],
)


@router.post(
    "/generate",
    response_model=GeneratedQuestionResult,
    summary="Generate and independently validate draft questions",
    responses={
        401: {"description": "Missing or invalid internal service authentication"},
        503: {"description": "Internal authentication is not configured"},
    },
    description=(
        "Internal AI endpoint. It only returns a fully validated draft batch; "
        "the backend owns job state, persistence, review, and publication."
    ),
)
async def generate_questions(
    request: GenerationRequest,
    service: QuestionGenerationService = Depends(get_question_generation_service),
) -> GeneratedQuestionResult:
    if request.question_count > service.settings.question_max_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="questionCount exceeds the configured maximum",
        )
    return await service.generate(request)
