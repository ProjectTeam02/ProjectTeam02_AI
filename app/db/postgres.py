# 파일 역할: PostgreSQL 연결과 SQLAlchemy 데이터 모델을 관리합니다.
"""Compatibility facade for the renamed database connection module.

The ``_engine`` alias is intentionally retained because local tests and older
scripts monkeypatch it for database-free table ownership checks.
"""

from app.db import connection as _connection

_engine = _connection._engine

session_factory = _connection.session_factory
get_session = _connection.get_session
dispose_engine = _connection.dispose_engine


async def create_tables() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    original_engine = _connection._engine
    _connection._engine = _engine
    try:
        await _connection.create_tables()
    finally:
        _connection._engine = original_engine

__all__ = ["create_tables", "dispose_engine", "get_session", "session_factory"]
