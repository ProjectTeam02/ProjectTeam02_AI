from __future__ import annotations

import hashlib
import math

from llama_index.core.embeddings import BaseEmbedding
from llama_index.embeddings.openai import OpenAIEmbedding

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError

from .llm_factory import OPENROUTER_BASE_URL, _api_key, _validate_model


class DeterministicEmbedding(BaseEmbedding):
    """Offline embedding fallback; production should configure an embedding provider."""

    dimension: int = 1536

    def _get_text_embedding(self, text: str) -> list[float]:
        return self._embed(text)

    def _get_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    async def _aget_query_embedding(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, text: str) -> list[float]:
        values = [0.0] * self.dimension
        for token in text.lower().split():
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            values[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]


class ValidatedOpenAIEmbedding(OpenAIEmbedding):
    """Factory-created OpenAI-compatible embedding with dimension checks.

    LlamaIndex's OpenAIEmbedding performs the HTTP request.  This small
    subclass validates every returned vector before it can reach pgvector, so
    a provider/model mismatch cannot silently corrupt an index.
    """

    expected_dimension: int = 1536

    @staticmethod
    def _validate(vector, expected: int):
        if len(vector) != expected:
            raise ConfigurationError(
                "embedding dimension mismatch: "
                f"expected {expected}, received {len(vector)}"
            )
        return vector

    def _get_text_embedding(self, text):
        return self._validate(
            super()._get_text_embedding(text), self.expected_dimension
        )

    def _get_query_embedding(self, query):
        return self._validate(
            super()._get_query_embedding(query), self.expected_dimension
        )

    async def _aget_text_embedding(self, text):
        return self._validate(
            await super()._aget_text_embedding(text), self.expected_dimension
        )

    async def _aget_query_embedding(self, query):
        return self._validate(
            await super()._aget_query_embedding(query), self.expected_dimension
        )


class EmbeddingModelFactory:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create(self):
        if self.settings.embedding_provider == "deterministic":
            return DeterministicEmbedding(
                model_name="deterministic-local",
                dimension=self.settings.embedding_dimension,
            )
        provider = self.settings.embedding_provider
        if provider in {"openai", "openrouter"}:
            _validate_model(provider, self.settings.embedding_model, "embedding")
            if (
                provider == "openrouter"
                and self.settings.embedding_model == "openai/text-embedding-3-small"
                and self.settings.embedding_dimension != 1536
            ):
                raise ConfigurationError(
                    "openai/text-embedding-3-small on OpenRouter requires "
                    "EMBEDDING_DIMENSION=1536"
                )
            api_key = _api_key(self.settings, provider)
            api_base = self.settings.embedding_base_url
            if provider == "openrouter":
                api_base = api_base or OPENROUTER_BASE_URL
            # LlamaIndex 0.14 validates ``model`` against its OpenAI enum
            # before honoring ``model_name``.  Use the unqualified suffix for
            # that compatibility check while sending the provider-qualified
            # ID (via model_name) to OpenRouter.
            llamaindex_model = self.settings.embedding_model
            if provider == "openrouter":
                llamaindex_model = self.settings.embedding_model.split("/", 1)[1]
            kwargs = {
                "model": llamaindex_model,
                "model_name": self.settings.embedding_model,
                "api_key": api_key,
                "api_base": api_base,
                "dimensions": self.settings.embedding_dimension,
                "timeout": self.settings.llm_timeout_seconds,
            }
            if provider == "openrouter":
                return ValidatedOpenAIEmbedding(
                    **kwargs, expected_dimension=self.settings.embedding_dimension
                )
            return OpenAIEmbedding(
                **kwargs
            )
        raise ConfigurationError(
            f"unsupported embedding provider: {provider!r}"
        )
