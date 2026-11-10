from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.dependencies import (
    get_question_generation_service,
    get_question_job_service,
    require_internal_api,
)
from app.question_generation.jobs import (
    DuplicateRequestError,
    QuestionGenerationJobService,
)
from app.question_generation.service import QuestionGenerationService
from app.schemas.question_generation import (
    GeneratedQuestionResult,
    GenerationJobRequest,
    GenerationJobResponse,
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


@router.post(
    "/jobs",
    response_model=GenerationJobResponse,
    response_model_by_alias=True,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Register, execute, and persist a validated question-generation job",
    responses={
        401: {"description": "Missing or invalid internal service authentication"},
        409: {"description": "requestId was reused with a different payload"},
    },
)
async def create_question_job(
    request: GenerationJobRequest,
    jobs: QuestionGenerationJobService = Depends(get_question_job_service),
) -> GenerationJobResponse:
    if request.question_count > jobs.generator.settings.question_max_count:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="questionCount exceeds the configured maximum",
        )
    try:
        job = await jobs.submit(request)
    except DuplicateRequestError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return job.response()


@router.get(
    "/jobs/{job_id}",
    response_model=GenerationJobResponse,
    response_model_by_alias=True,
    summary="Read question-generation execution and review state",
    responses={
        401: {"description": "Missing or invalid internal service authentication"},
        404: {"description": "Question-generation job not found"},
    },
)
async def get_question_job(
    job_id: UUID,
    jobs: QuestionGenerationJobService = Depends(get_question_job_service),
) -> GenerationJobResponse:
    job = await jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="question generation job not found")
    return job.response()
