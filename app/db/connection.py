from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import (
    AIUserMemory,
    Base,
    RAGChunk,
    RAGDocument,
    RAGIndexConfiguration,
)

_engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def session_factory() -> AsyncSession:
    return _session_factory()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with _session_factory() as session:
        yield session


async def create_tables() -> None:
    """Create only FastAPI-owned local tables.

    ``ai_conversations``, ``ai_messages``, ``ai_message_sources`` and
    ``ai_requests`` belong to Node.js according to the current ERD. They remain
    mapped for legacy compatibility but are deliberately excluded here.
    Production deployments should use the backend migration owner instead of
    calling this helper.
    """
    tables = [
        AIUserMemory.__table__,
        RAGDocument.__table__,
        RAGChunk.__table__,
        RAGIndexConfiguration.__table__,
    ]
    async with _engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=tables)


async def dispose_engine() -> None:
    await _engine.dispose()
