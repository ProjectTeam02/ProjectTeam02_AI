from pydantic import BaseModel, Field


class TutorRequest(BaseModel):
    user_id: str
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    learning_concept: str | None = None
    incorrect_answer: str | None = None


class Citation(BaseModel):
    document_id: str
    chunk_id: str
    title: str | None = None
    source: str
    version: str | None = None
    score: float | None = None


class TutorResponse(BaseModel):
    answer: str
    conversation_id: str | None = None
    citations: list[Citation] = Field(default_factory=list)
