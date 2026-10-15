from fastapi import APIRouter

from app.schemas.memory import MemoryResponse

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/{user_id}", response_model=list[MemoryResponse])
async def list_memories(user_id: str) -> list[MemoryResponse]:
    # TODO: connect the memory repository.
    return []
