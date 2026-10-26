from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AIUserMemory


@dataclass(slots=True)
class MemoryRecord:
    id: str
    user_id: str
    content: str
    source: str | None
    created_at: datetime | None


class MemoryRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, user_id: str, content: str, source: str | None = None
    ) -> MemoryRecord:
        memory = AIUserMemory(user_id=user_id, content=content, source=source)
        self.session.add(memory)
        await self.session.commit()
        await self.session.refresh(memory)
        return self._record(memory)

    async def list_by_user(self, user_id: str) -> list[MemoryRecord]:
        result = await self.session.execute(
            select(AIUserMemory)
            .where(AIUserMemory.user_id == user_id)
            .order_by(AIUserMemory.created_at.desc())
        )
        return [self._record(memory) for memory in result.scalars().all()]

    @staticmethod
    def _record(memory: AIUserMemory) -> MemoryRecord:
        return MemoryRecord(
            id=str(memory.id),
            user_id=memory.user_id,
            content=memory.content,
            source=memory.source,
            created_at=memory.created_at,
        )


class InMemoryMemoryRepository:
    """Small repository used by tests and local runs without PostgreSQL."""

    def __init__(self) -> None:
        self._items: list[MemoryRecord] = []

    async def create(
        self, user_id: str, content: str, source: str | None = None
    ) -> MemoryRecord:
        record = MemoryRecord(
            str(uuid.uuid4()), user_id, content, source, datetime.now().astimezone()
        )
        self._items.append(record)
        return record

    async def list_by_user(self, user_id: str) -> list[MemoryRecord]:
        return [item for item in reversed(self._items) if item.user_id == user_id]
