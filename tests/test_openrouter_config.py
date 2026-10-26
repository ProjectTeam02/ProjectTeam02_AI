import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.api.dependencies as dependencies
from app.api.dependencies import require_internal_api
from app.core.config import Settings
from app.core.exceptions import ConfigurationError
from app.main import app
from app.rag.llamaindex.embedding_model import (
    EmbeddingModelFactory,
    ValidatedOpenAIEmbedding,
)
from app.rag.llamaindex.llm_factory import LLMFactory


def openrouter_settings(**overrides) -> Settings:
    values = {
        "openrouter_api_key": "sk-or-v1-test-only",
        "llm_provider": "openrouter",
        "llm_model": "openai/gpt-4o-mini",
        "embedding_provider": "openrouter",
        "embedding_model": "openai/text-embedding-3-small",
        "embedding_dimension": 1536,
    }
    values.update(overrides)
    return Settings(**values)


def test_env_file_loads_openrouter_settings_without_printing_secret(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENROUTER_API_KEY=sk-or-v1-local-test\n"
        "LLM_PROVIDER=openrouter\n"
        "LLM_MODEL=openai/gpt-4o-mini\n"
        "EMBEDDING_PROVIDER=openrouter\n"
        "EMBEDDING_MODEL=openai/text-embedding-3-small\n"
        "EMBEDDING_DIMENSION=1536\n",
        encoding="utf-8",
    )
    settings = Settings(_env_file=env_file)
    assert settings.openrouter_api_key == "sk-or-v1-local-test"
    assert settings.llm_model == "openai/gpt-4o-mini"
    assert settings.embedding_dimension == 1536


def test_openrouter_llm_factory_uses_openrouter_key_and_base_url():
    llm = LLMFactory(openrouter_settings()).create()
    assert llm.model == "openai/gpt-4o-mini"
    assert llm.api_base == "https://openrouter.ai/api/v1"
    assert llm.api_key == "sk-or-v1-test-only"
    assert llm.timeout == 30.0
    assert llm.metadata.context_window > 0


def test_openrouter_embedding_factory_uses_qualified_model_and_dimension():
    embedding = EmbeddingModelFactory(openrouter_settings()).create()
    assert isinstance(embedding, ValidatedOpenAIEmbedding)
    assert embedding.model_name == "openai/text-embedding-3-small"
    assert embedding.api_base == "https://openrouter.ai/api/v1"
    assert embedding.dimensions == 1536
    assert embedding.expected_dimension == 1536


def test_openai_provider_remains_supported():
    settings = Settings(
        openai_api_key="sk-openai-test",
        llm_provider="openai",
        llm_model="gpt-4o-mini",
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
    )
    assert LLMFactory(settings).create().model == "gpt-4o-mini"
    assert EmbeddingModelFactory(settings).create().model_name == (
        "text-embedding-3-small"
    )


def test_missing_provider_key_is_a_configuration_error():
    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        LLMFactory(openrouter_settings(openrouter_api_key=None)).create()
    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        EmbeddingModelFactory(openrouter_settings(openrouter_api_key=None)).create()


def test_openrouter_model_id_and_dimension_are_validated():
    with pytest.raises(ConfigurationError, match="provider-qualified"):
        LLMFactory(openrouter_settings(llm_model="gpt-4o-mini")).create()
    with pytest.raises(ConfigurationError, match="EMBEDDING_DIMENSION=1536"):
        EmbeddingModelFactory(openrouter_settings(embedding_dimension=1024)).create()


def test_embedding_response_dimension_is_checked_before_pgvector_write():
    with pytest.raises(ConfigurationError, match="expected 1536, received 3"):
        ValidatedOpenAIEmbedding._validate([0.0, 0.0, 0.0], 1536)


def test_missing_openrouter_key_returns_safe_api_configuration_error(monkeypatch):
    monkeypatch.setattr(
        dependencies,
        "get_settings",
        lambda: Settings(openrouter_api_key=None),
    )
    app.dependency_overrides[require_internal_api] = lambda: None
    try:
        response = TestClient(app).post(
            "/internal/v1/tutor/answer",
            json={
                "requestId": str(uuid.uuid4()),
                "conversationId": str(uuid.uuid4()),
                "userId": str(uuid.uuid4()),
                "question": "기준금리가 뭐야?",
                "modelTier": "BASIC",
                "history": [],
            },
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 503
    assert response.json()["detail"] == "AI provider configuration is unavailable"
