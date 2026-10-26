from app.db.repositories.memory_repository import InMemoryMemoryRepository
from app.schemas.memory import MemoryCreate, MemoryResponse


class MemoryService:
    def __init__(self, repository=None):
        self.repository = repository or InMemoryMemoryRepository()

    async def save(
        self, memory: MemoryCreate, authenticated_user_id: str | None = None
    ) -> MemoryResponse:
        self._check_owner(memory.user_id, authenticated_user_id)
        record = await self.repository.create(
            memory.user_id, memory.content, memory.source
        )
        return MemoryResponse(
            id=record.id,
            user_id=record.user_id,
            content=record.content,
            source=record.source,
            created_at=record.created_at,
        )

    async def list_for_user(
        self, user_id: str, authenticated_user_id: str | None = None
    ) -> list[MemoryResponse]:
        self._check_owner(user_id, authenticated_user_id)
        records = await self.repository.list_by_user(user_id)
        return [
            MemoryResponse(
                id=record.id,
                user_id=record.user_id,
                content=record.content,
                source=record.source,
                created_at=record.created_at,
            )
            for record in records
        ]

    @staticmethod
    def _check_owner(user_id: str, authenticated_user_id: str | None) -> None:
        if authenticated_user_id is not None and user_id != authenticated_user_id:
            raise PermissionError("user does not own this memory")
