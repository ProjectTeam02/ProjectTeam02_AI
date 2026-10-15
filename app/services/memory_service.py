from app.schemas.memory import MemoryCreate, MemoryResponse


class MemoryService:
    async def save(self, memory: MemoryCreate) -> MemoryResponse:
        raise NotImplementedError("Connect MemoryRepository before saving memories.")

    async def list_for_user(self, user_id: str) -> list[MemoryResponse]:
        raise NotImplementedError("Connect MemoryRepository before listing memories.")
