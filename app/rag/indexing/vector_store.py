# 파일 역할: LlamaIndex 기반 RAG 검색·생성·메모리·인덱싱 기능을 제공합니다.
from __future__ import annotations

from sqlalchemy.engine import URL, make_url

from app.core.config import Settings, get_settings

# asyncpg는 `ssl=`, psycopg(libpq)는 `sslmode=`를 받는다. 같은 DATABASE_URL에서
# 두 드라이버용 접속 문자열을 만들 때 SSL 옵션 이름을 서로 맞춰 준다.
_ASYNC_DRIVER = "postgresql+asyncpg"
_SYNC_DRIVER = "postgresql+psycopg"


def _render(url: URL) -> str:
    """Render a URL with its real password.

    PGVectorStore calls ``str()`` on URL objects, and SQLAlchemy 2.x renders
    ``str(URL)`` with the password masked as ``***``. Passing the URL object
    therefore made RDS reject ``ai_user`` with "password authentication failed".
    """
    return url.render_as_string(hide_password=False)


def build_connection_strings(database_url: str) -> tuple[str, str]:
    """Return ``(sync_psycopg_url, async_asyncpg_url)`` for PGVectorStore."""
    base = make_url(database_url)
    query = dict(base.query)
    ssl_value = query.pop("ssl", None) or query.pop("sslmode", None)
    query.pop("sslmode", None)

    sync_query = dict(query)
    async_query = dict(query)
    if ssl_value is not None:
        sync_query["sslmode"] = ssl_value
        async_query["ssl"] = ssl_value

    sync_url = base.set(drivername=_SYNC_DRIVER, query=sync_query)
    async_url = base.set(drivername=_ASYNC_DRIVER, query=async_query)
    return _render(sync_url), _render(async_url)


class VectorStoreFactory:
    """Build the configured LlamaIndex PostgreSQL/pgvector store."""

    def __init__(self, settings: Settings | None = None):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        self.settings = settings or get_settings()

    def create(self, collection: str | None = None):
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        from llama_index.vector_stores.postgres import PGVectorStore

        sync_url, async_url = build_connection_strings(self.settings.database_url)
        return PGVectorStore(
            connection_string=sync_url,
            async_connection_string=async_url,
            table_name=collection or self.settings.vector_store_collection,
            schema_name=self.settings.vector_store_schema,
            embed_dim=self.settings.embedding_dimension,
            use_jsonb=True,
            perform_setup=self.settings.vector_store_perform_setup,
            initialization_fail_on_error=True,
        )
