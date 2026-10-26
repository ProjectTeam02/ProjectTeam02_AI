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
    if user_id != current_user_id:
        raise HTTPException(status_code=403, detail="memory access denied")
    return await service.list_for_user(user_id, authenticated_user_id=current_user_id)
