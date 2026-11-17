"""Question-generation job registration, execution, and idempotency.

The repository is deliberately small and in-process because this service does not
own the Node.js job queue.  It still models the production contract: one
request-id maps to one job, only an all-green batch is exposed as
``PENDING_REVIEW``, and a cancelled execution is terminally failed instead of
being left in ``RUNNING`` forever.  A database-backed adapter can implement the
same methods when the queue/storage owner is agreed with Node.js.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.schemas.question_generation import (
    GeneratedQuestionResult,
    GenerationErrorCode,
    GenerationJobRequest,
    GenerationJobResponse,
)

logger = logging.getLogger(__name__)


class DuplicateRequestError(ValueError):
    """The same request id was reused with a different generation payload."""


@dataclass(slots=True)
class QuestionJob:
    job_id: uuid.UUID
    request_id: uuid.UUID
    fingerprint: str
    execution_status: str = "REGISTERED"
    review_status: str | None = None
    failure_step: str | None = None
    failure_code: str | None = None
    failure_detail: str | None = None
    attempt_count: int = 0
    result: GeneratedQuestionResult | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def response(self) -> GenerationJobResponse:
        return GenerationJobResponse(
            jobId=self.job_id,
            requestId=self.request_id,
            executionStatus=self.execution_status,
            reviewStatus=self.review_status,
            failureStep=self.failure_step,
            failureCode=self.failure_code,
            failureDetail=self.failure_detail,
            attemptCount=self.attempt_count,
            createdAt=self.created_at,
            updatedAt=self.updated_at,
            result=self.result,
        )


class InMemoryQuestionJobRepository:
    """Atomic process-local job repository used by API smoke tests and CI."""

    def __init__(self) -> None:
        self._jobs: dict[uuid.UUID, QuestionJob] = {}
        self._by_request: dict[uuid.UUID, uuid.UUID] = {}
        self._lock = asyncio.Lock()

    async def register(self, request: GenerationJobRequest) -> tuple[QuestionJob, bool]:
        fingerprint = _fingerprint(request)
        async with self._lock:
            existing_id = self._by_request.get(request.request_id)
            if existing_id is not None:
                existing = self._jobs[existing_id]
                if existing.fingerprint != fingerprint:
                    raise DuplicateRequestError(
                        "requestId was already used with a different payload"
                    )
                return existing, False
            job = QuestionJob(
                job_id=uuid.uuid4(),
                request_id=request.request_id,
                fingerprint=fingerprint,
            )
            self._jobs[job.job_id] = job
            self._by_request[request.request_id] = job.job_id
            return job, True

    async def get(self, job_id: uuid.UUID) -> QuestionJob | None:
        async with self._lock:
            return self._jobs.get(job_id)

    async def start(self, job_id: uuid.UUID) -> QuestionJob:
        async with self._lock:
            job = self._jobs[job_id]
            job.execution_status = "RUNNING"
            job.attempt_count += 1
            job.updated_at = datetime.now(timezone.utc)
            return job

    async def complete(
        self, job_id: uuid.UUID, result: GeneratedQuestionResult
    ) -> QuestionJob:
        async with self._lock:
            job = self._jobs[job_id]
            job.execution_status = "COMPLETED"
            job.review_status = "PENDING_REVIEW"
            job.result = result.model_copy(update={"job_id": job.job_id})
            job.failure_step = None
            job.failure_code = None
            job.failure_detail = None
            job.updated_at = datetime.now(timezone.utc)
            return job

    async def fail(
        self,
        job_id: uuid.UUID,
        *,
        step: str,
        code: str,
        detail: str,
    ) -> QuestionJob:
        async with self._lock:
            job = self._jobs[job_id]
            job.execution_status = "FAILED"
            job.review_status = None
            job.result = None
            job.failure_step = step
            job.failure_code = code
            job.failure_detail = detail[:1000]
            job.updated_at = datetime.now(timezone.utc)
            return job

    async def clear(self) -> None:
        async with self._lock:
            self._jobs.clear()
            self._by_request.clear()


class QuestionGenerationJobService:
    def __init__(self, generator, repository: InMemoryQuestionJobRepository) -> None:
        self.generator = generator
        self.repository = repository

    async def submit(self, request: GenerationJobRequest) -> QuestionJob:
        job, created = await self.repository.register(request)
        if not created:
            return job

        await self.repository.start(job.job_id)
        logger.info(
            "question_workflow",
            extra={
                "job_id": str(job.job_id),
                "request_id": str(job.request_id),
                "workflow_stage": "generation_started",
                "attempt_count": job.attempt_count,
                "failure_code": None,
            },
        )
        try:
            result = await self.generator.generate(request)
            if result.status != "COMPLETED" or not result.questions:
                await self.repository.fail(
                    job.job_id,
                    step=_failure_step(result.error),
                    code=(result.error.value if result.error else "GENERATION_FAILED"),
                    detail=(
                        result.error_detail or "question batch did not pass validation"
                    ),
                )
                logger.warning(
                    "question_workflow_failed",
                    extra={
                        "job_id": str(job.job_id),
                        "request_id": str(job.request_id),
                        "workflow_stage": _failure_step(result.error),
                        "evidence_document_ids": [
                            reference.document_id
                            for reference in result.evidence_references
                        ],
                        "prompt_version": result.prompt_versions,
                        "model_id": getattr(self.generator.llm, "model_id", None),
                        "attempt_count": job.attempt_count,
                        "failure_code": (
                            result.error.value if result.error else "GENERATION_FAILED"
                        ),
                    },
                )
            else:
                await self.repository.complete(job.job_id, result)
                logger.info(
                    "question_workflow",
                    extra={
                        "job_id": str(job.job_id),
                        "request_id": str(job.request_id),
                        "workflow_stage": "pending_review_saved",
                        "evidence_document_ids": [
                            reference.document_id
                            for reference in result.evidence_references
                        ],
                        "prompt_version": result.prompt_versions,
                        "model_id": getattr(self.generator.llm, "model_id", None),
                        "attempt_count": job.attempt_count,
                        "failure_code": None,
                    },
                )
        except BaseException:
            # ``finally`` cannot persist a useful reason for cancellation, so make
            # cancellation explicit while allowing the cancellation to propagate.
            await self.repository.fail(
                job.job_id,
                step="execution",
                code="EXECUTION_INTERRUPTED",
                detail="question generation execution was interrupted",
            )
            logger.exception(
                "question_workflow interrupted",
                extra={
                    "job_id": str(job.job_id),
                    "request_id": str(job.request_id),
                    "workflow_stage": "execution",
                    "failure_code": "EXECUTION_INTERRUPTED",
                },
            )
            raise
        return await self.repository.get(job.job_id)

    async def get(self, job_id: uuid.UUID) -> QuestionJob | None:
        return await self.repository.get(job_id)


def _fingerprint(request: GenerationJobRequest) -> str:
    payload = request.model_dump(mode="json", exclude={"request_id"})
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def _failure_step(error: GenerationErrorCode | None) -> str:
    if error == GenerationErrorCode.INSUFFICIENT_EVIDENCE:
        return "evidence_lookup"
    if error == GenerationErrorCode.CONFLICTING_EVIDENCE:
        return "qg"
    return "qv_or_code_validation"
