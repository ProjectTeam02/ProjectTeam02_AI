from sqlalchemy.ext.asyncio import AsyncSession


class MemoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_by_user(self, user_id: str):
        raise NotImplementedError
