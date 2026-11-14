# 파일 역할: PostgreSQL 연결과 SQLAlchemy 데이터 모델을 관리합니다.
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models import (
    Base,
    RAGChunk,
    RAGDocument,
    RAGIndexConfiguration,
)

_engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
_session_factory = async_sessionmaker(_engine, expire_on_commit=False)


def session_factory() -> AsyncSession:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return _session_factory()


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    async with _session_factory() as session:
        yield session


async def create_tables() -> None:
    """Create the RAG metadata tables on a local development database only.

    The schema owner is the backend repository (``database/sql/init/02~04``).
    Never call this against RDS. The LlamaIndex vector table is created by the
    backend SQL as well; set ``VECTOR_STORE_PERFORM_SETUP=true`` only for a
    throwaway local database.
    """
    tables = [
        RAGDocument.__table__,
        RAGChunk.__table__,
        RAGIndexConfiguration.__table__,
    ]
    async with _engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all, tables=tables)


async def dispose_engine() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    await _engine.dispose()
