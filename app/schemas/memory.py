# 파일 역할: API 요청·응답의 데이터 구조와 입력 검증 규칙을 정의합니다.
from datetime import datetime

from pydantic import BaseModel


class MemoryCreate(BaseModel):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    user_id: str
    content: str
    source: str | None = None


class MemoryResponse(MemoryCreate):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    id: str
    created_at: datetime | None = None
