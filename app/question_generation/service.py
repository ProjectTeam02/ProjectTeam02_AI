from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Iterable
from typing import Any

from pydantic import ValidationError

from app.core.config import Settings
from app.question_generation.evidence import (
    EmptyEvidenceProvider,
    EmptyExistingQuestionProvider,
    EvidenceProvider,
    ExistingQuestionProvider,
)
from app.question_generation.llm import JsonLLM, LLMConfigurationError, LLMRequestError
from app.question_generation.prompts import (
    QG_PROMPT_VERSION,
    QUESTION_GENERATION_SYSTEM_PROMPT,
    QUESTION_VALIDATION_SYSTEM_PROMPT,
    QV_PROMPT_VERSION,
)
from app.schemas.question_generation import (
    EvidenceSource,
    ExistingQuestion,
    GeneratedQuestion,
    GeneratedQuestionBatch,
    GeneratedQuestionResult,
    GenerationErrorCode,
    GenerationRequest,
    ValidationDecision,
    ValidationRecord,
    ValidationResult,
)


class QuestionGenerationService:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: JsonLLM,
        evidence_provider: EvidenceProvider | None = None,
        existing_question_provider: ExistingQuestionProvider | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.evidence_provider = evidence_provider or EmptyEvidenceProvider()
        self.existing_question_provider = (
            existing_question_provider or EmptyExistingQuestionProvider()
        )

    async def generate(self, request: GenerationRequest) -> GeneratedQuestionResult:
        if request.question_count > self.settings.question_max_count:
            return self._failed(
                request,
                GenerationErrorCode.GENERATION_FAILED,
                "question count exceeds configured limit",
            )
        evidence = await self.evidence_provider.search(request)
        evidence = _approved_evidence(evidence)
        if not evidence:
            return self._failed(request, GenerationErrorCode.INSUFFICIENT_EVIDENCE)

        existing = await self.existing_question_provider.list_similar(request)
        try:
            batch = await self._generate_batch(request, evidence, existing)
        except ModelGenerationError as exc:
            return self._failed(request, exc.error)
        except (LLMConfigurationError, LLMRequestError, ValueError, ValidationError):
            return self._failed(request, GenerationErrorCode.GENERATION_FAILED)

        code_error = validate_batch(
            batch,
            request=request,
            evidence=evidence,
            existing=existing,
        )
        if code_error:
            return self._failed(
                request, GenerationErrorCode.GENERATION_FAILED, code_error
            )

        validated: list[GeneratedQuestion] = []
        records: list[ValidationRecord] = []
        for index, candidate in enumerate(batch.questions):
            current = candidate
            approved = False
            for attempt in range(1, self.settings.question_max_revision_attempts + 2):
                try:
                    verdict = await self._validate_question(
                        request=request,
                        candidate=current,
                        evidence=evidence,
                        existing=existing,
                    )
                except (
                    LLMConfigurationError,
                    LLMRequestError,
                    ValueError,
                    ValidationError,
                ):
                    return self._failed(
                        request,
                        GenerationErrorCode.GENERATION_FAILED,
                        "content validation failed",
                    )

                records.append(
                    ValidationRecord(
                        questionIndex=index,
                        attempt=attempt,
                        decision=verdict.decision,
                        independentAnswerIndex=verdict.independent_answer_index,
                        issues=verdict.issues,
                        feedback=verdict.feedback,
                    )
                )
                if verdict.decision == ValidationDecision.APPROVE:
                    if verdict.independent_answer_index != current.correct_answer_index:
                        return self._failed(
                            request,
                            GenerationErrorCode.GENERATION_FAILED,
                            "independent answer does not match generated answer",
                        )
                    validated.append(current)
                    approved = True
                    break
                if verdict.decision == ValidationDecision.REJECT:
                    return self._failed(
                        request,
                        GenerationErrorCode.GENERATION_FAILED,
                        "content validator rejected a question",
                    )
                if attempt > self.settings.question_max_revision_attempts:
                    break
                try:
                    current = await self._revise_question(
                        request=request,
                        candidate=current,
                        evidence=evidence,
                        existing=existing,
                        feedback=verdict.feedback,
                    )
                    revision_error = validate_question(
                        current,
                        request=request,
                        evidence=evidence,
                        existing=existing,
                        batch_questions=[*validated, current],
                    )
                    if revision_error:
                        return self._failed(
                            request,
                            GenerationErrorCode.GENERATION_FAILED,
                            revision_error,
                        )
                except (
                    LLMConfigurationError,
                    LLMRequestError,
                    ValueError,
                    ValidationError,
                ):
                    return self._failed(
                        request,
                        GenerationErrorCode.GENERATION_FAILED,
                        "question revision failed",
                    )
            if not approved:
                return self._failed(
                    request,
                    GenerationErrorCode.GENERATION_FAILED,
                    "revision limit exceeded",
                )

        if len(validated) != request.question_count:
            return self._failed(
                request,
                GenerationErrorCode.GENERATION_FAILED,
                "validated question count is incomplete",
            )
        source_ids = sorted(
            {source_id for question in validated for source_id in question.source_ids}
        )
        return GeneratedQuestionResult(
            status="COMPLETED",
            topic=request.topic,
            difficulty=request.difficulty,
            questions=validated,
            sourceIds=source_ids,
            validation=records,
            promptVersions={"qg": QG_PROMPT_VERSION, "qv": QV_PROMPT_VERSION},
        )

    async def _generate_batch(
        self,
        request: GenerationRequest,
        evidence: list[EvidenceSource],
        existing: list[ExistingQuestion],
    ) -> GeneratedQuestionBatch:
        raw = await self.llm.complete_json(
            system_prompt=QUESTION_GENERATION_SYSTEM_PROMPT,
            user_payload=_generation_payload(request, evidence, existing),
        )
        parsed = _parse_json_object(raw)
        batch = GeneratedQuestionBatch.model_validate(parsed)
        if batch.error is not None:
            raise ModelGenerationError(batch.error)
        return batch

    async def _revise_question(
        self,
        *,
        request: GenerationRequest,
        candidate: GeneratedQuestion,
        evidence: list[EvidenceSource],
        existing: list[ExistingQuestion],
        feedback: str,
    ) -> GeneratedQuestion:
        raw = await self.llm.complete_json(
            system_prompt=QUESTION_GENERATION_SYSTEM_PROMPT,
            user_payload={
                **_generation_payload(request, evidence, existing),
                "revision": {
                    "candidate": candidate.model_dump(by_alias=True),
                    "feedback": feedback,
                },
                "requestedQuestionCount": 1,
            },
        )
        parsed = _parse_json_object(raw)
        batch = GeneratedQuestionBatch.model_validate(parsed)
        if batch.error is not None or len(batch.questions) != 1:
            raise ValueError("revision did not return one question")
        return batch.questions[0]

    async def _validate_question(
        self,
        *,
        request: GenerationRequest,
        candidate: GeneratedQuestion,
        evidence: list[EvidenceSource],
        existing: list[ExistingQuestion],
    ) -> ValidationResult:
        raw = await self.llm.complete_json(
            system_prompt=QUESTION_VALIDATION_SYSTEM_PROMPT,
            user_payload={
                "request": {
                    "topic": request.topic,
                    "difficulty": request.difficulty,
                    "learningObjectives": request.learning_objectives,
                },
                "question": {
                    "questionType": candidate.question_type,
                    "question": candidate.question,
                    "choices": candidate.choices,
                    "explanation": candidate.explanation,
                    "learningObjective": candidate.learning_objective,
                    "sourceIds": candidate.source_ids,
                },
                "evidence": [source.model_dump(mode="json") for source in evidence],
                "existingQuestions": [
                    question.model_dump(mode="json") for question in existing
                ],
            },
        )
        verdict = ValidationResult.model_validate(_parse_json_object(raw))
        if verdict.decision == ValidationDecision.APPROVE and verdict.issues:
            raise ValueError("approved validation response contains issues")
        if verdict.decision != ValidationDecision.APPROVE and (
            not verdict.issues or not verdict.feedback.strip()
        ):
            raise ValueError("non-approved validation response lacks feedback")
        return verdict

    def _failed(
        self,
        request: GenerationRequest,
        error: GenerationErrorCode,
        detail: str | None = None,
    ) -> GeneratedQuestionResult:
        return GeneratedQuestionResult(
            status="FAILED",
            topic=request.topic,
            difficulty=request.difficulty,
            questions=[],
            error=error,
            errorDetail=detail,
            promptVersions={"qg": QG_PROMPT_VERSION, "qv": QV_PROMPT_VERSION},
        )


def validate_batch(
    batch: GeneratedQuestionBatch,
    *,
    request: GenerationRequest,
    evidence: list[EvidenceSource],
    existing: list[ExistingQuestion],
) -> str | None:
    if batch.topic != request.topic or batch.difficulty != request.difficulty:
        return "generation metadata does not match request"
    if len(batch.questions) != request.question_count:
        return "generated question count does not match request"

    normalized_questions: set[str] = set()
    for candidate in batch.questions:
        error = validate_question(
            candidate,
            request=request,
            evidence=evidence,
            existing=existing,
            batch_questions=batch.questions,
        )
        if error:
            return error
        key = _normalize(candidate.question)
        if key in normalized_questions:
            return "duplicate questions in generated batch"
        normalized_questions.add(key)
    return None


class ModelGenerationError(ValueError):
    def __init__(self, error: GenerationErrorCode) -> None:
        super().__init__(error.value)
        self.error = error


def validate_question(
    candidate: GeneratedQuestion,
    *,
    request: GenerationRequest,
    evidence: list[EvidenceSource],
    existing: Iterable[ExistingQuestion],
    batch_questions: Iterable[GeneratedQuestion],
) -> str | None:
    if candidate.learning_objective.casefold() not in {
        objective.casefold() for objective in request.learning_objectives
    }:
        return "learning objective is outside the request"
    evidence_by_id = {source.source_id: source for source in evidence}
    if not candidate.source_ids or any(
        source_id not in evidence_by_id for source_id in candidate.source_ids
    ):
        return "question references an unavailable evidence source"
    if len({_normalize(choice) for choice in candidate.choices}) != 4:
        return "choices must be unique after normalization"
    if any(_forbidden_choice(choice) for choice in candidate.choices):
        return "choices contain a forbidden catch-all option"
    if _normalize(candidate.question) in {
        _normalize(item.question) for item in existing
    }:
        return "question duplicates an existing question"
    if sum(
        _normalize(candidate.question) == _normalize(item.question)
        for item in batch_questions
    ) > 1:
        return "question duplicates another generated question"
    return None


def _generation_payload(
    request: GenerationRequest,
    evidence: list[EvidenceSource],
    existing: list[ExistingQuestion],
) -> dict[str, Any]:
    return {
        "request": {
            "topic": request.topic,
            "difficulty": request.difficulty,
            "questionCount": request.question_count,
            "learningObjectives": request.learning_objectives,
        },
        "evidence": [source.model_dump(mode="json") for source in evidence],
        "existingQuestions": [
            question.model_dump(mode="json") for question in existing
        ],
    }


def _approved_evidence(evidence: Iterable[EvidenceSource]) -> list[EvidenceSource]:
    return [
        source
        for source in evidence
        if source.review_status.casefold() == "approved"
        and source.content.strip()
        and source.document_version.strip()
    ]


def _parse_json_object(raw: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        raise ValueError("LLM response is not an object or JSON string")
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("LLM response JSON must be an object")
    return value


def _normalize(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _forbidden_choice(value: str) -> bool:
    normalized = _normalize(value).replace(" ", "")
    return any(
        phrase in normalized
        for phrase in ("모두정답", "정답없음", "alloftheabove", "noneoftheabove")
    )
