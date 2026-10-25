from typing import Any

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class TutorRequest(BaseModel):
    user_id: str
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    learning_concept: str | None = None
    incorrect_answer: str | None = None


class Citation(BaseModel):
    source_id: str | None = None
    document_id: str
    chunk_id: str
    title: str | None = None
    source: str
    url: str | None = None
    version: str | None = None
    score: float | None = None


class TutorResponse(BaseModel):
    answer: str
    conversation_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool = False


class WrongAnswerContext(BaseModel):
    question_id: str | None = Field(default=None, alias="questionId")
    user_answer: str | None = Field(default=None, alias="userAnswer")
    correct_answer: str | None = Field(default=None, alias="correctAnswer")
    explanation: str | None = None

    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    def as_prompt_text(self) -> str | None:
        values = [
            ("문항", self.question_id),
            ("학습자 답", self.user_answer),
            ("검증된 정답", self.correct_answer),
            ("검증된 해설", self.explanation),
        ]
        text = "\n".join(f"{label}: {value}" for label, value in values if value)
        return text or None


class InternalTutorRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=255, alias="userId")
    conversation_id: str | None = Field(default=None, alias="conversationId")
    request_id: str = Field(min_length=1, max_length=255, alias="requestId")
    stage_id: str = Field(min_length=1, max_length=255, alias="stageId")
    concept_id: str = Field(min_length=1, max_length=255, alias="conceptId")
    question: str = Field(
        min_length=1,
        max_length=4000,
        validation_alias=AliasChoices("question", "userQuestion"),
    )
    wrong_answer_context: WrongAnswerContext | None = Field(
        default=None, alias="wrongAnswerContext"
    )

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class InternalCitation(BaseModel):
    source_id: str = Field(alias="sourceId")
    document_id: str = Field(alias="documentId")
    document_version: str | None = Field(default=None, alias="documentVersion")
    title: str | None = None
    url: str | None = None

    model_config = ConfigDict(populate_by_name=True)


class InternalTutorResponse(BaseModel):
    conversation_id: str = Field(alias="conversationId")
    answer: str
    citations: list[InternalCitation] = Field(default_factory=list)
    grounded: bool
    request_id: str = Field(alias="requestId")
    model_name: str | None = Field(default=None, alias="modelName")
    usage: dict[str, Any] | None = None

    model_config = ConfigDict(populate_by_name=True)
