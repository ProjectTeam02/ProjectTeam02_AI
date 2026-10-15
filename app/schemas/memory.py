from datetime import datetime

from pydantic import BaseModel


class MemoryCreate(BaseModel):
    user_id: str
    content: str
    source: str | None = None


class MemoryResponse(MemoryCreate):
    id: str
    created_at: datetime | None = None
