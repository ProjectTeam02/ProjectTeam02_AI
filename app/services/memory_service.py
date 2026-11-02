# 파일 역할: API와 RAG·저장소 사이의 서비스 업무 흐름을 조정합니다.
from app.repositories.memory_repository import InMemoryMemoryRepository
from app.schemas.memory import MemoryCreate, MemoryResponse


class MemoryService:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    def __init__(self, repository=None):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        self.repository = repository or InMemoryMemoryRepository()

    async def save(
        self, memory: MemoryCreate, authenticated_user_id: str | None = None
    ) -> MemoryResponse:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
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
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
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
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        if authenticated_user_id is not None and user_id != authenticated_user_id:
            raise PermissionError("user does not own this memory")
