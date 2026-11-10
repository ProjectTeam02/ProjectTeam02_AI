from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Difficulty(StrEnum):
    EASY = "EASY"
    MEDIUM = "MEDIUM"
    HARD = "HARD"


class QuestionType(StrEnum):
    CONCEPT = "CONCEPT"
    COMPARISON = "COMPARISON"
    SCENARIO = "SCENARIO"
    APPLICATION = "APPLICATION"


class GenerationErrorCode(StrEnum):
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    GENERATION_FAILED = "GENERATION_FAILED"


class GenerationRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        str_strip_whitespace=True,
    )

    topic: Annotated[str, Field(min_length=1, max_length=120)]
    chapter_id: Annotated[str | None, Field(alias="chapterId", max_length=120)] = None
    difficulty: Difficulty
    question_count: Annotated[int, Field(alias="questionCount", ge=1, le=100)]
    learning_objectives: Annotated[
        list[Annotated[str, Field(min_length=1, max_length=240)]],
        Field(alias="learningObjectives", min_length=1, max_length=10),
    ]

    @field_validator("learning_objectives")
    @classmethod
    def reject_duplicate_objectives(cls, values: list[str]) -> list[str]:
        normalized = {value.casefold() for value in values}
        if len(normalized) != len(values):
            raise ValueError("learningObjectives must not contain duplicates")
        return values


class EvidenceSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: Annotated[str, Field(min_length=1, max_length=200)]
    document_id: Annotated[str, Field(min_length=1, max_length=200)]
    document_version: Annotated[str, Field(min_length=1, max_length=120)]
    content: Annotated[str, Field(min_length=1, max_length=30_000)]
    review_status: str = "approved"
    publisher: str | None = None
    as_of_date: date | None = None


class ExistingQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[str, Field(min_length=1, max_length=2_000)]
    choices: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list
    )


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, str_strip_whitespace=True
    )

    question_type: QuestionType = Field(alias="questionType")
    question: Annotated[str, Field(min_length=10, max_length=2_000)]
    choices: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        min_length=4, max_length=4
    )
    correct_answer_index: Annotated[int, Field(alias="correctAnswerIndex", ge=0, le=3)]
    explanation: Annotated[str, Field(min_length=10, max_length=3_000)]
    learning_objective: Annotated[str, Field(alias="learningObjective", min_length=1)]
    source_ids: list[Annotated[str, Field(min_length=1, max_length=200)]] = Field(
        alias="sourceIds", min_length=1, max_length=10
    )

    @field_validator("source_ids")
    @classmethod
    def reject_duplicate_sources(cls, values: list[str]) -> list[str]:
        if len(set(values)) != len(values):
            raise ValueError("sourceIds must not contain duplicates")
        return values


class GeneratedQuestionBatch(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    topic: Annotated[str, Field(min_length=1, max_length=120)]
    difficulty: Difficulty
    questions: list[GeneratedQuestion]
    error: GenerationErrorCode | None = None


class ValidationDecision(StrEnum):
    APPROVE = "APPROVE"
    REVISE = "REVISE"
    REJECT = "REJECT"


class ValidationResult(BaseModel):
    model_config = ConfigDict(
        extra="forbid", populate_by_name=True, str_strip_whitespace=True
    )

    decision: ValidationDecision
    independent_answer_index: Annotated[
        int, Field(alias="independentAnswerIndex", ge=0, le=3)
    ]
    issues: list[Annotated[str, Field(min_length=1, max_length=500)]] = Field(
        default_factory=list, max_length=20
    )
    feedback: Annotated[str, Field(max_length=2_000)] = ""


class ValidationRecord(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    question_index: int = Field(alias="questionIndex", ge=0)
    attempt: int = Field(ge=1)
    decision: ValidationDecision
    independent_answer_index: int | None = Field(
        default=None, alias="independentAnswerIndex"
    )
    issues: list[str] = Field(default_factory=list)
    feedback: str = ""


class GeneratedQuestionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    status: str
    topic: str
    difficulty: Difficulty
    questions: list[GeneratedQuestion] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list, alias="sourceIds")
    validation: list[ValidationRecord] = Field(default_factory=list)
    error: GenerationErrorCode | None = None
    error_detail: str | None = Field(default=None, alias="errorDetail")
    prompt_versions: dict[str, str] = Field(
        default_factory=dict, alias="promptVersions"
    )
    evidence_references: list["EvidenceReference"] = Field(
        default_factory=list, alias="evidenceReferences"
    )
    job_id: UUID | None = Field(default=None, alias="jobId")


class EvidenceReference(BaseModel):
    """Immutable approval/version trace attached to a generated batch."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    source_id: str = Field(alias="sourceId", min_length=1, max_length=200)
    document_id: str = Field(alias="documentId", min_length=1, max_length=200)
    document_version: str = Field(alias="documentVersion", min_length=1, max_length=120)


class GenerationJobRequest(GenerationRequest):
    """Idempotent internal request used by the persisted question workflow."""

    request_id: UUID = Field(alias="requestId")


class GenerationJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    job_id: UUID = Field(alias="jobId")
    request_id: UUID = Field(alias="requestId")
    execution_status: str = Field(alias="executionStatus")
    review_status: str | None = Field(default=None, alias="reviewStatus")
    failure_step: str | None = Field(default=None, alias="failureStep")
    failure_code: str | None = Field(default=None, alias="failureCode")
    failure_detail: str | None = Field(default=None, alias="failureDetail")
    attempt_count: int = Field(alias="attemptCount", ge=0)
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    result: GeneratedQuestionResult | None = None
