from pydantic import BaseModel, Field


class TutorRequest(BaseModel):
    user_id: str
    message: str = Field(min_length=1)
    conversation_id: str | None = None


class TutorResponse(BaseModel):
    answer: str
    conversation_id: str | None = None
    citations: list[str] = []
