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
    original_engine = _connection._engine
    _connection._engine = _engine
    try:
        await _connection.create_tables()
    finally:
        _connection._engine = original_engine

__all__ = ["create_tables", "dispose_engine", "get_session", "session_factory"]
