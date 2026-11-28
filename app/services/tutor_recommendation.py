"""Safe, deterministic tutor diagnosis and next-action selection.

The Backend owns learner records and eligibility.  This module only derives a
small client-safe summary from already validated request context and selects a
question from the Backend-provided candidate list.
"""

from __future__ import annotations

import re

from app.schemas.tutor import (
    CONCEPT_CODE_MAX,
    TUTOR_CONTRACT_SCHEMA_VERSION,
    UUID_PATTERN,
    ActionPriority,
    InternalTutorRequest,
    MisconceptionType,
    ProposedAction,
    ProposedActionType,
    TutoringDiagnosis,
    TutoringMeta,
    TutoringStrategy,
)

_STRATEGIES = {
    MisconceptionType.KNOWLEDGE_GAP: "FOUNDATION_EXPLANATION_V1",
    MisconceptionType.RELATION_ERROR: "RELATION_COMPARISON_V1",
    MisconceptionType.CAUSAL_ERROR: "CAUSAL_CHAIN_V1",
    MisconceptionType.APPLICATION_ERROR: "APPLICATION_STEPWISE_V1",
    MisconceptionType.UNCERTAIN: "DIAGNOSTIC_CHECK_V1",
}

_REASONS = {
    MisconceptionType.KNOWLEDGE_GAP: "기초 개념 이해가 부족할 가능성이 있습니다.",
    MisconceptionType.RELATION_ERROR: "개념 사이의 관계를 혼동했을 가능성이 있습니다.",
    MisconceptionType.CAUSAL_ERROR: "원인과 결과의 연결을 혼동했을 가능성이 있습니다.",
    MisconceptionType.APPLICATION_ERROR: (
        "개념을 상황에 적용하는 과정에서 어려움이 있을 수 있습니다."
    ),
    MisconceptionType.UNCERTAIN: "확정할 수 있는 근거가 부족해 추가 확인이 필요합니다.",
}


_UUID = re.compile(UUID_PATTERN)


def _uuid_or_none(value: str | None) -> str | None:
    """Backend persists only UUID identifiers; anything else is dropped."""
    return value if value and _UUID.fullmatch(value) else None


def _code_or_none(value: str | None) -> str | None:
    return value if value and len(value) <= CONCEPT_CODE_MAX else None


def _concept_code(request: InternalTutorRequest) -> str | None:
    return _code_or_none(_raw_concept_code(request))


def _raw_concept_code(request: InternalTutorRequest) -> str | None:
    if request.context and request.context.concept_code:
        return request.context.concept_code
    profile = (
        request.personalized_context.learner_profile
        if request.personalized_context
        else None
    )
    if profile and profile.concept_code:
        return profile.concept_code
    graph = (
        request.personalized_context.concept_graph_context
        if request.personalized_context
        else None
    )
    return graph.current_concept_code if graph else None


def _evidence_question_ids(request: InternalTutorRequest) -> list[str]:
    """Return only question IDs explicitly supplied by Backend evidence rows."""
    context = request.personalized_context
    if context is None:
        return []
    values = [
        item.question_id
        for item in context.diagnosis_evidence
        if _uuid_or_none(item.question_id)
    ]
    result: list[str] = []
    for value in values:
        if value.lower() not in {existing.lower() for existing in result}:
            result.append(value)
    return result[:20]


def _diagnosis(request: InternalTutorRequest) -> TutoringDiagnosis:
    context = request.personalized_context
    hypothesis = (
        context.misconception_hypotheses[0]
        if context and context.misconception_hypotheses
        else None
    )
    evidence_ids = _evidence_question_ids(request)
    observations = (hypothesis.observation_count or 0) if hypothesis else 0
    raw_type = hypothesis.hypothesis_type if hypothesis else MisconceptionType.UNCERTAIN
    try:
        hypothesis_type = MisconceptionType(raw_type)
    except ValueError:
        hypothesis_type = MisconceptionType.UNCERTAIN

    # One wrong answer is an observation, never a confirmed diagnosis.  Missing
    # question-level evidence is also fail-closed.
    sufficient = observations >= 2 and bool(evidence_ids)
    if not sufficient:
        hypothesis_type = MisconceptionType.UNCERTAIN
    confidence = hypothesis.confidence if hypothesis and sufficient else 0.0
    if confidence is None:
        confidence = 0.0
    summary = (
        hypothesis.rationale.strip()
        if hypothesis and hypothesis.rationale and sufficient
        else _REASONS[hypothesis_type]
    )
    return TutoringDiagnosis(
        misconceptionType=hypothesis_type,
        confidence=confidence,
        evidenceQuestionIds=evidence_ids,
        needsFollowup=not sufficient,
        reasoningSummary=summary,
    )


def build_tutoring_meta(request: InternalTutorRequest) -> TutoringMeta:
    diagnosis = _diagnosis(request)
    context = request.personalized_context
    supplied_strategy = context.teaching_strategy if context else None
    strategy = TutoringStrategy(
        strategyId=(
            supplied_strategy.strategy_id
            if supplied_strategy
            else _STRATEGIES[diagnosis.misconception_type]
        ),
        strategyVersion=(
            supplied_strategy.strategy_version if supplied_strategy else "1.0"
        ),
    )
    return TutoringMeta(
        schemaVersion=TUTOR_CONTRACT_SCHEMA_VERSION,
        conceptCode=_concept_code(request),
        diagnosis=diagnosis,
        strategy=strategy,
    )


def _priority(
    request: InternalTutorRequest, diagnosis: TutoringDiagnosis
) -> ActionPriority:
    profile = (
        request.personalized_context.learner_profile
        if request.personalized_context
        else None
    )
    if profile and profile.weakness_score is not None and profile.weakness_score >= 0.6:
        return ActionPriority.HIGH
    if diagnosis.misconception_type is not MisconceptionType.UNCERTAIN:
        return ActionPriority.MEDIUM
    return ActionPriority.LOW


def build_proposed_action(
    request: InternalTutorRequest, meta: TutoringMeta
) -> ProposedAction:
    concept_code = meta.concept_code
    priority = _priority(request, meta.diagnosis)
    candidates = request.eligible_question_candidates
    if candidates:
        candidate = next(
            (
                item
                for item in candidates
                if concept_code and item.concept_code == concept_code
            ),
            candidates[0],
        )
        return ProposedAction(
            type=ProposedActionType.SOLVE_QUESTION,
            conceptCode=candidate.concept_code,
            questionId=candidate.question_id,
            stageId=candidate.stage_id,
            attemptId=candidate.attempt_id,
            reason="Backend가 현재 응시 가능한 문항으로 검증한 후보입니다.",
            priority=priority,
        )

    context = request.context
    profile = (
        request.personalized_context.learner_profile
        if request.personalized_context
        else None
    )
    stage_id = _uuid_or_none(context.stage_id if context else None)
    attempt_id = _uuid_or_none(context.attempt_id if context else None)
    stage_id = stage_id or _uuid_or_none(
        profile.current_stage_id if profile else None
    )
    if stage_id and attempt_id:
        return ProposedAction(
            type=ProposedActionType.CONTINUE_LEARNING,
            conceptCode=concept_code,
            stageId=stage_id,
            attemptId=attempt_id,
            reason="진행 중인 응시를 기존 학습 흐름에서 계속하세요.",
            priority=priority,
        )
    if stage_id:
        return ProposedAction(
            type=ProposedActionType.START_STAGE,
            conceptCode=concept_code,
            stageId=stage_id,
            reason="새 학습이 필요하면 이 공개 Stage를 시작하세요.",
            priority=priority,
        )
    if concept_code:
        return ProposedAction(
            type=ProposedActionType.REVIEW_CONCEPT,
            conceptCode=concept_code,
            reason="추천 문항이 없어 개념 복습부터 안내합니다.",
            priority=priority,
        )
    return ProposedAction(
        type=ProposedActionType.NONE,
        reason="현재 확인된 학습 문맥으로는 안전한 다음 행동을 정할 수 없습니다.",
        priority=ActionPriority.LOW,
    )


def recommend(request: InternalTutorRequest) -> tuple[TutoringMeta, ProposedAction]:
    meta = build_tutoring_meta(request)
    return meta, build_proposed_action(request, meta)
