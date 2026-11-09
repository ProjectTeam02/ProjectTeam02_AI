# 파일 역할: HTTP API 계층의 의존성 또는 라우터를 정의합니다.
from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import get_current_user_id, get_memory_service
from app.schemas.memory import MemoryResponse
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/{user_id}", response_model=list[MemoryResponse])
async def list_memories(
    user_id: str,
    current_user_id: str = Depends(get_current_user_id),
    service: MemoryService = Depends(get_memory_service),
) -> list[MemoryResponse]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    if user_id != current_user_id:
        raise HTTPException(status_code=403, detail="memory access denied")
    return await service.list_for_user(user_id, authenticated_user_id=current_user_id)
