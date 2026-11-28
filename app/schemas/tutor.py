# 파일 역할: API 요청·응답의 데이터 구조와 입력 검증 규칙을 정의합니다.
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

# Backend(tutorMetadata.dto.js / aiInternalResponse.dto.js) 계약 상수.
# 값을 바꾸면 docs/contract.md와 docs/contracts/*.schema.json 스냅샷도 함께 갱신한다.
TUTOR_CONTRACT_SCHEMA_VERSION = "1.0"
UUID_PATTERN = r"^[0-9a-fA-F]{8}-(?:[0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$"
CONCEPT_CODE_MAX = 30


class TutorRequest(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    user_id: str
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    learning_concept: str | None = None
    incorrect_answer: str | None = None


class Citation(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    source_id: str | None = None
    document_id: str
    chunk_id: str
    title: str | None = None
    source: str
    url: str | None = None
    version: str | None = None
    score: float | None = None


class TutorResponse(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    answer: str
    conversation_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool = False


class ModelTier(StrEnum):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    BASIC = "BASIC"
    ADVANCED = "ADVANCED"


class HistoryRole(StrEnum):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    USER = "USER"
    ASSISTANT = "ASSISTANT"


class GroundingStatus(StrEnum):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    GROUNDED = "GROUNDED"
    INSUFFICIENT = "INSUFFICIENT"


class TutorHistoryItem(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    sequence_no: int = Field(ge=1, alias="sequenceNo")
    role: HistoryRole
    content: str = Field(min_length=1, max_length=4000)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        value = value.strip()
        if not value:
            raise ValueError("content must not be blank")
        return value


class TutorLearningContext(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    entry_point: str | None = Field(default=None, max_length=50, alias="entryPoint")
    topic_id: str | None = Field(default=None, max_length=255, alias="topicId")
    stage_id: str | None = Field(default=None, max_length=255, alias="stageId")
    concept_id: str | None = Field(default=None, max_length=255, alias="conceptId")
    concept_code: str | None = Field(
        default=None, min_length=1, max_length=100, alias="conceptCode"
    )
    question_id: str | None = Field(default=None, max_length=255, alias="questionId")
    attempt_id: str | None = Field(default=None, max_length=255, alias="attemptId")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TutorKnowledgeScope(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    concept_codes: list[str] = Field(
        default_factory=list, max_length=100, alias="conceptCodes"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("concept_codes")
    @classmethod
    def validate_concept_codes(cls, values: list[str]) -> list[str]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        normalized = [value.strip() for value in values]
        if any(not value or len(value) > 100 for value in normalized):
            raise ValueError("conceptCodes entries must contain 1 to 100 characters")
        if len(set(normalized)) != len(normalized):
            raise ValueError("conceptCodes must not contain duplicates")
        return normalized


class LearnerProfileContext(BaseModel):
    """Backend-provided learner signals used only as personalization hints.

    Scores are deliberately optional and normalized to the inclusive 0..1 range.
    The Backend contract must define the conversion from percentage values before
    this field is enabled in production.
    """

    concept_code: str | None = Field(
        default=None, min_length=1, max_length=30, alias="conceptCode"
    )
    accuracy_rate: float | None = Field(
        default=None, ge=0.0, le=1.0, alias="accuracyRate"
    )
    recent_incorrect_count: int | None = Field(
        default=None, ge=0, le=10000, alias="recentIncorrectCount"
    )
    estimated_mastery: float | None = Field(
        default=None, ge=0.0, le=1.0, alias="estimatedMastery"
    )
    weakness_score: float | None = Field(
        default=None, ge=0.0, le=1.0, alias="weaknessScore"
    )
    last_studied_at: datetime | None = Field(default=None, alias="lastStudiedAt")
    current_stage_id: str | None = Field(
        default=None, max_length=255, alias="currentStageId"
    )
    data_sufficiency: str | None = Field(
        default=None, max_length=20, alias="dataSufficiency"
    )
    uncertainty: float | None = Field(default=None, ge=0.0, le=1.0)
    weakness_components: dict[str, float] = Field(
        default_factory=dict, max_length=10, alias="weaknessComponents"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("weakness_components")
    @classmethod
    def validate_weakness_components(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not key.strip() or len(key.strip()) > 40 for key in values):
            raise ValueError("weaknessComponents keys must contain 1 to 40 characters")
        if any(value < 0.0 or value > 1.0 for value in values.values()):
            raise ValueError("weaknessComponents values must be between 0 and 1")
        return values


class ConceptGraphNode(BaseModel):
    """A Backend-supplied graph edge target, not an AI-owned graph record."""

    concept_code: str = Field(min_length=1, max_length=30, alias="conceptCode")
    title: str | None = Field(default=None, max_length=255)
    relationship_type: str = Field(
        default="PREREQUISITE", min_length=1, max_length=40, alias="relationshipType"
    )
    relation_review_status: str | None = Field(
        default=None, max_length=30, alias="relationReviewStatus"
    )
    learner_concept_mastery: float | None = Field(
        default=None, ge=0.0, le=1.0, alias="learnerConceptMastery"
    )
    depth: int = Field(default=1, ge=1, le=5)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ConceptGraphContext(BaseModel):
    current_concept_code: str | None = Field(
        default=None, min_length=1, max_length=30, alias="currentConceptCode"
    )
    prerequisite_concepts: list[ConceptGraphNode] = Field(
        default_factory=list, max_length=50, alias="prerequisiteConcepts"
    )
    related_concepts: list[ConceptGraphNode] = Field(
        default_factory=list, max_length=50, alias="relatedConcepts"
    )
    learner_concept_mastery: dict[str, float] = Field(
        default_factory=dict, max_length=50, alias="learnerConceptMastery"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("learner_concept_mastery")
    @classmethod
    def validate_mastery_map(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not code.strip() or len(code.strip()) > 30 for code in values):
            raise ValueError(
                "learnerConceptMastery keys must contain 1 to 30 characters"
            )
        if any(value < 0.0 or value > 1.0 for value in values.values()):
            raise ValueError("learnerConceptMastery values must be between 0 and 1")
        return values


class MisconceptionHypothesisContext(BaseModel):
    """Unconfirmed diagnosis data reserved for the later diagnosis contract."""

    hypothesis_type: str = Field(min_length=1, max_length=40, alias="hypothesisType")
    status: str = Field(default="UNCONFIRMED", min_length=1, max_length=30)
    concept_code: str | None = Field(
        default=None, min_length=1, max_length=30, alias="conceptCode"
    )
    evidence_ids: list[str] = Field(
        default_factory=list, max_length=20, alias="evidenceIds"
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    rationale: str | None = Field(default=None, max_length=500)
    observation_count: int | None = Field(
        default=None, ge=0, le=10000, alias="observationCount"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class DiagnosisEvidenceContext(BaseModel):
    evidence_id: str = Field(min_length=1, max_length=255, alias="evidenceId")
    evidence_type: str = Field(min_length=1, max_length=40, alias="evidenceType")
    review_status: str | None = Field(default=None, max_length=30, alias="reviewStatus")
    question_id: str | None = Field(default=None, max_length=255, alias="questionId")
    document_id: str | None = Field(default=None, max_length=255, alias="documentId")
    chunk_id: str | None = Field(default=None, max_length=255, alias="chunkId")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class RecentAssessmentContext(BaseModel):
    assessment_id: str = Field(min_length=1, max_length=255, alias="assessmentId")
    question_id: str | None = Field(default=None, max_length=255, alias="questionId")
    concept_code: str | None = Field(
        default=None, min_length=1, max_length=30, alias="conceptCode"
    )
    is_correct: bool | None = Field(default=None, alias="isCorrect")
    assessed_at: datetime | None = Field(default=None, alias="assessedAt")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TeachingStrategyContext(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=100, alias="strategyId")
    strategy_version: str = Field(min_length=1, max_length=50, alias="strategyVersion")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class PersonalizedTutorContext(BaseModel):
    learner_profile: LearnerProfileContext | None = Field(
        default=None, alias="learnerProfile"
    )
    misconception_hypotheses: list[MisconceptionHypothesisContext] = Field(
        default_factory=list, max_length=10, alias="misconceptionHypotheses"
    )
    diagnosis_evidence: list[DiagnosisEvidenceContext] = Field(
        default_factory=list, max_length=20, alias="diagnosisEvidence"
    )
    recent_assessments: list[RecentAssessmentContext] = Field(
        default_factory=list, max_length=10, alias="recentAssessments"
    )
    teaching_strategy: TeachingStrategyContext | None = Field(
        default=None, alias="teachingStrategy"
    )
    concept_graph_context: ConceptGraphContext | None = Field(
        default=None, alias="conceptGraphContext"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class VerifiedSourceContext(BaseModel):
    """Backend-approved source metadata; the AI server never approves it."""

    document_id: str = Field(alias="documentId", min_length=1, max_length=255)
    document_version: str | None = Field(default=None, alias="documentVersion")
    title: str | None = Field(default=None, max_length=255)
    review_status: str | None = Field(default=None, alias="reviewStatus")
    license_review_status: str | None = Field(default=None, alias="licenseReviewStatus")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class VerifiedTutorContext(BaseModel):
    """Fail-closed Backend verification boundary for Tutor retrieval."""

    verification_status: str = Field(
        min_length=1, max_length=30, alias="verificationStatus"
    )
    concept_id: str | None = Field(default=None, alias="conceptId")
    concept_code: str | None = Field(
        default=None, min_length=1, max_length=100, alias="conceptCode"
    )
    version: int | None = Field(default=None, ge=1)
    title: str | None = Field(default=None, max_length=255)
    short_definition: str | None = Field(
        default=None, max_length=1000, alias="shortDefinition"
    )
    source_document_ids: list[str] = Field(
        default_factory=list, max_length=100, alias="sourceDocumentIds"
    )
    sources: list[VerifiedSourceContext] = Field(default_factory=list, max_length=100)
    prerequisite_concepts: list[ConceptGraphNode] = Field(
        default_factory=list, max_length=50, alias="prerequisiteConcepts"
    )
    blocking_reasons: list[str] = Field(
        default_factory=list, max_length=50, alias="blockingReasons"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class MisconceptionType(StrEnum):
    KNOWLEDGE_GAP = "KNOWLEDGE_GAP"
    RELATION_ERROR = "RELATION_ERROR"
    CAUSAL_ERROR = "CAUSAL_ERROR"
    APPLICATION_ERROR = "APPLICATION_ERROR"
    UNCERTAIN = "UNCERTAIN"


class ProposedActionType(StrEnum):
    SOLVE_QUESTION = "SOLVE_QUESTION"
    START_STAGE = "START_STAGE"
    REVIEW_CONCEPT = "REVIEW_CONCEPT"
    CONTINUE_LEARNING = "CONTINUE_LEARNING"
    NONE = "NONE"


class ActionPriority(StrEnum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class EligibleQuestionCandidate(BaseModel):
    """A Backend-verified question that the AI may recommend, never discover."""

    question_id: str = Field(pattern=UUID_PATTERN, alias="questionId")
    concept_code: str = Field(
        min_length=1, max_length=CONCEPT_CODE_MAX, alias="conceptCode"
    )
    stage_id: str = Field(pattern=UUID_PATTERN, alias="stageId")
    attempt_id: str = Field(pattern=UUID_PATTERN, alias="attemptId")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TutoringDiagnosis(BaseModel):
    misconception_type: MisconceptionType = Field(alias="misconceptionType")
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_question_ids: list[
        Annotated[str, StringConstraints(pattern=UUID_PATTERN)]
    ] = Field(
        default_factory=list,
        max_length=20,
        alias="evidenceQuestionIds",
        description="본인이 제출한 오답 문항 UUID. 근거가 없으면 []",
    )
    needs_followup: bool = Field(alias="needsFollowup")
    reasoning_summary: str = Field(
        min_length=1, max_length=500, alias="reasoningSummary"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("evidence_question_ids")
    @classmethod
    def unique_evidence(cls, value: list[str]) -> list[str]:
        if len({item.lower() for item in value}) != len(value):
            raise ValueError("evidenceQuestionIds must be unique")
        return value


class TutoringStrategy(BaseModel):
    strategy_id: str = Field(min_length=1, max_length=100, alias="strategyId")
    strategy_version: str = Field(min_length=1, max_length=50, alias="strategyVersion")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class TutoringMeta(BaseModel):
    """Client-safe diagnosis summary. Backend rejects unknown keys (strict)."""

    schema_version: Literal["1.0"] = Field(
        alias="schemaVersion",
        description="계약 버전. Backend는 정확히 '1.0'만 허용",
    )
    concept_code: str | None = Field(
        default=None, min_length=1, max_length=CONCEPT_CODE_MAX, alias="conceptCode"
    )
    diagnosis: TutoringDiagnosis
    strategy: TutoringStrategy

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ProposedAction(BaseModel):
    """Next learning action. Backend re-validates every identifier before saving."""

    type: ProposedActionType
    concept_code: str | None = Field(
        default=None, min_length=1, max_length=CONCEPT_CODE_MAX, alias="conceptCode"
    )
    question_id: str | None = Field(
        default=None, pattern=UUID_PATTERN, alias="questionId"
    )
    stage_id: str | None = Field(default=None, pattern=UUID_PATTERN, alias="stageId")
    attempt_id: str | None = Field(
        default=None, pattern=UUID_PATTERN, alias="attemptId"
    )
    reason: str = Field(min_length=1, max_length=500)
    priority: ActionPriority

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def validate_action_fields(self):
        if self.type is ProposedActionType.SOLVE_QUESTION:
            if not all(
                (self.question_id, self.stage_id, self.attempt_id, self.concept_code)
            ):
                raise ValueError(
                    "SOLVE_QUESTION requires questionId, stageId, attemptId, "
                    "and conceptCode"
                )
        elif self.type is ProposedActionType.START_STAGE:
            if not self.stage_id or self.question_id or self.attempt_id:
                raise ValueError(
                    "START_STAGE requires stageId and forbids questionId/attemptId"
                )
        elif self.type is ProposedActionType.REVIEW_CONCEPT:
            if not self.concept_code or self.question_id or self.attempt_id:
                raise ValueError(
                    "REVIEW_CONCEPT requires conceptCode and forbids "
                    "questionId/attemptId"
                )
        elif self.type is ProposedActionType.CONTINUE_LEARNING:
            if self.question_id or not (self.stage_id or self.attempt_id):
                raise ValueError(
                    "CONTINUE_LEARNING requires stageId or attemptId and "
                    "forbids questionId"
                )
        elif any((self.question_id, self.stage_id, self.attempt_id)):
            raise ValueError("NONE must not contain questionId, stageId, or attemptId")
        return self


class InternalTutorRequest(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    request_id: UUID = Field(alias="requestId")
    conversation_id: UUID = Field(alias="conversationId")
    user_id: UUID = Field(alias="userId")
    question: str = Field(
        min_length=1,
        max_length=4000,
        validation_alias=AliasChoices("question", "userQuestion"),
    )
    model_tier: ModelTier = Field(alias="modelTier")
    history: list[TutorHistoryItem] = Field(default_factory=list, max_length=50)
    summary: str | None = Field(default=None, max_length=12000)
    summary_until_seq: int | None = Field(default=None, ge=1, alias="summaryUntilSeq")
    context: TutorLearningContext | None = None
    knowledge_scope: TutorKnowledgeScope | None = Field(
        default=None, alias="knowledgeScope"
    )
    personalized_context: PersonalizedTutorContext | None = Field(
        default=None, alias="personalizedContext"
    )
    verified_context: VerifiedTutorContext | None = Field(
        default=None, alias="verifiedContext"
    )
    eligible_question_candidates: list[EligibleQuestionCandidate] = Field(
        default_factory=list, max_length=10, alias="eligibleQuestionCandidates"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @field_validator("question")
    @classmethod
    def reject_blank_question(cls, value: str) -> str:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value

    @field_validator("summary")
    @classmethod
    def normalize_summary(cls, value: str | None) -> str | None:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        if value is None:
            return None
        value = value.strip()
        return value or None

    @model_validator(mode="after")
    def validate_history_contract(self):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        sequences = [item.sequence_no for item in self.history]
        if sequences != sorted(sequences) or len(set(sequences)) != len(sequences):
            raise ValueError("history sequenceNo values must be unique and increasing")
        if (self.summary is None) != (self.summary_until_seq is None):
            raise ValueError("summary and summaryUntilSeq must be supplied together")
        question_ids = [item.question_id for item in self.eligible_question_candidates]
        if len(set(question_ids)) != len(question_ids):
            raise ValueError(
                "eligibleQuestionCandidates questionId values must be unique"
            )
        return self


class InternalTutorSource(BaseModel):
    """Citation persisted by Backend into tutor.ai_message_sources.

    Lengths mirror Backend SOURCE_LIMITS. ``reviewStatus``/``licenseReviewStatus``
    are AI-side trace snapshots only; Backend ignores them and re-checks
    ``ai.rag_documents.review_status`` itself.
    """

    document_id: str = Field(min_length=1, max_length=255, alias="documentId")
    document_version: str | None = Field(
        default=None, max_length=100, alias="documentVersion"
    )
    chunk_id: str = Field(min_length=1, max_length=255, alias="chunkId")
    title_snapshot: str | None = Field(
        default=None, max_length=500, alias="titleSnapshot"
    )
    concept_code: str | None = Field(
        default=None, max_length=CONCEPT_CODE_MAX, alias="conceptCode"
    )
    rank: int = Field(ge=1, le=32767)
    relevance_score: float | None = Field(
        default=None, ge=0.0, le=1.0, alias="relevanceScore"
    )
    review_status: str | None = Field(
        default=None,
        max_length=30,
        alias="reviewStatus",
        description="검색 시점 문서 내용 검수 상태 스냅샷(정보용, 권한 판단 아님)",
    )
    license_review_status: str | None = Field(
        default=None,
        max_length=30,
        alias="licenseReviewStatus",
        description="Backend verifiedContext가 준 라이선스 검수 상태. 없으면 null",
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class InternalTutorUsage(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    model_id: str | None = Field(default=None, max_length=100, alias="modelId")
    embedding_model_id: str | None = Field(
        default=None, max_length=100, alias="embeddingModelId"
    )
    input_tokens: int | None = Field(default=None, ge=0, alias="inputTokens")
    output_tokens: int | None = Field(default=None, ge=0, alias="outputTokens")
    latency_ms: int = Field(ge=0, alias="latencyMs")
    cache_hit: bool = Field(alias="cacheHit")
    retrieval_strategy: str = Field(
        min_length=1, max_length=50, alias="retrievalStrategy"
    )
    estimated_cost: float | None = Field(default=None, ge=0, alias="estimatedCost")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class InternalTutorResponse(BaseModel):
    """FastAPI -> Backend tutor answer. Contract: docs/contract.md (v1.0)."""

    request_id: UUID = Field(
        alias="requestId", description="요청의 requestId와 반드시 같다"
    )
    answer: str = Field(min_length=1)
    rewritten_query: str = Field(alias="rewrittenQuery")
    grounding_status: GroundingStatus = Field(
        alias="groundingStatus",
        description="GROUNDED: 승인 근거로 답변. INSUFFICIENT: 근거 부족(Fail-Closed)",
    )
    history_from_seq: int | None = Field(
        default=None, ge=1, alias="historyFromSeq"
    )
    sources: list[InternalTutorSource] = Field(
        default_factory=list, description="rank는 1부터 고유"
    )
    usage: InternalTutorUsage
    tutoring_meta: TutoringMeta | None = Field(
        default=None,
        alias="tutoringMeta",
        description="TUTOR_METADATA_ENABLED=true일 때만 Backend가 저장·노출",
    )
    proposed_action: ProposedAction | None = Field(
        default=None,
        alias="proposedAction",
        description="Backend가 후보·소유권을 재검증한 뒤에만 저장",
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    @model_validator(mode="after")
    def unique_source_ranks(self):
        ranks = [item.rank for item in self.sources]
        if len(set(ranks)) != len(ranks):
            raise ValueError("sources rank values must be unique")
        return self
