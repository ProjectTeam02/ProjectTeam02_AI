# 파일 역할: API 요청·응답의 데이터 구조와 입력 검증 규칙을 정의합니다.
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


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

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class ConceptGraphNode(BaseModel):
    """A Backend-supplied graph edge target, not an AI-owned graph record."""

    concept_code: str = Field(
        min_length=1, max_length=30, alias="conceptCode"
    )
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
        return self


class InternalTutorSource(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    document_id: str = Field(alias="documentId")
    document_version: str | None = Field(default=None, alias="documentVersion")
    chunk_id: str = Field(alias="chunkId")
    title_snapshot: str | None = Field(default=None, alias="titleSnapshot")
    concept_code: str | None = Field(default=None, alias="conceptCode")
    rank: int = Field(ge=1)
    relevance_score: float | None = Field(
        default=None, ge=0.0, le=1.0, alias="relevanceScore"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class InternalTutorUsage(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    model_id: str | None = Field(default=None, alias="modelId")
    embedding_model_id: str | None = Field(default=None, alias="embeddingModelId")
    input_tokens: int | None = Field(default=None, ge=0, alias="inputTokens")
    output_tokens: int | None = Field(default=None, ge=0, alias="outputTokens")
    latency_ms: int = Field(ge=0, alias="latencyMs")
    cache_hit: bool = Field(alias="cacheHit")
    retrieval_strategy: str = Field(min_length=1, alias="retrievalStrategy")
    estimated_cost: float | None = Field(default=None, ge=0, alias="estimatedCost")
    currency: str | None = Field(default=None, pattern=r"^[A-Z]{3}$")

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class InternalTutorResponse(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    request_id: UUID = Field(alias="requestId")
    answer: str
    rewritten_query: str = Field(alias="rewrittenQuery")
    grounding_status: GroundingStatus = Field(alias="groundingStatus")
    history_from_seq: int | None = Field(default=None, alias="historyFromSeq")
    sources: list[InternalTutorSource] = Field(default_factory=list)
    usage: InternalTutorUsage

    model_config = ConfigDict(populate_by_name=True, extra="forbid")
