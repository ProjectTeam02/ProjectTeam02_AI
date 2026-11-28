# 파일 역할: AI 서버가 DB 구조를 만들지 않고 백엔드 소유 테이블을 쓰지 않는지 검증
from app.core.config import Settings
from app.db import connection
from app.db.models import Base, RAGChunk
from app.main import app
from app.rag.indexing import vector_store as vector_store_module


def test_models_map_only_ai_schema_rag_tables():
    # 함수 역할: 백엔드(tutor 스키마) 소유 테이블 모델이 없는지 확인합니다.
    assert set(Base.metadata.tables) == {
        "rag_documents",
        "rag_document_chunks",
        "rag_index_configurations",
    }


def test_rag_chunk_has_no_vector_column():
    # 함수 역할: 벡터는 LlamaIndex 테이블에만 저장하므로 청크에 벡터 컬럼이 없습니다.
    assert "embedding" not in RAGChunk.__table__.columns


def test_postgres_metadata_queries_use_configured_rag_schema():
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://u:p@localhost:5432/leren",
        vector_store_schema="ai",
    )
    assert connection._connect_args(settings) == {
        "server_settings": {"search_path": "ai,public"}
    }


def test_non_postgres_connections_do_not_receive_asyncpg_options():
    settings = Settings(_env_file=None, database_url="sqlite+aiosqlite:///./test.db")
    assert connection._connect_args(settings) == {}


def test_legacy_memory_api_is_removed():
    # 함수 역할: 예전 /api/memory 라우터가 더 이상 등록되지 않는지 확인합니다.
    paths = set(app.openapi()["paths"])
    assert paths
    assert not any(path.startswith("/api/memory") for path in paths)


def test_vector_store_does_not_create_tables_by_default(monkeypatch):
    # 함수 역할: 운영 기본값에서 LlamaIndex가 스키마·테이블을 만들지 않는지 확인합니다.
    captured = {}

    class FakePGVectorStore:
        # 클래스 역할: PGVectorStore 생성 인자만 기록합니다.
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import llama_index.vector_stores.postgres as postgres_module

    monkeypatch.setattr(postgres_module, "PGVectorStore", FakePGVectorStore)
    settings = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/leren",
        vector_store_schema="ai",
    )
    vector_store_module.VectorStoreFactory(settings).create()
    assert captured["perform_setup"] is False
    assert captured["schema_name"] == "ai"
    assert captured["table_name"] == "projectteam02"

    local = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/leren",
        vector_store_perform_setup=True,
    )
    vector_store_module.VectorStoreFactory(local).create()
    assert captured["perform_setup"] is True


def test_vector_store_passes_real_password_to_pgvector(monkeypatch):
    # 함수 역할: str(URL)이 비밀번호를 ***로 가려
    # ai_user 인증이 실패하던 회귀를 막습니다.
    captured = {}

    class FakePGVectorStore:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    import llama_index.vector_stores.postgres as postgres_module

    monkeypatch.setattr(postgres_module, "PGVectorStore", FakePGVectorStore)
    settings = Settings(
        _env_file=None,
        database_url="postgresql+asyncpg://ai_user:S3cr%40t%2Fx@db.example:5432/leren",
        vector_store_schema="ai",
    )
    vector_store_module.VectorStoreFactory(settings).create()
    for key in ("connection_string", "async_connection_string"):
        assert isinstance(captured[key], str)
        assert "***" not in captured[key]
        assert "S3cr%40t%2Fx@db.example" in captured[key]
    assert captured["connection_string"].startswith("postgresql+psycopg://")
    assert captured["async_connection_string"].startswith("postgresql+asyncpg://")


def test_vector_store_translates_ssl_option_per_driver():
    sync_url, async_url = vector_store_module.build_connection_strings(
        "postgresql+asyncpg://u:p@h:5432/leren?ssl=require"
    )
    assert sync_url.endswith("?sslmode=require")
    assert async_url.endswith("?ssl=require")

    sync_url, async_url = vector_store_module.build_connection_strings(
        "postgresql+asyncpg://u:p@h:5432/leren?sslmode=verify-full"
    )
    assert "sslmode=verify-full" in sync_url
    assert "ssl=verify-full" in async_url and "sslmode" not in async_url
