from __future__ import annotations

import hashlib
import math

from llama_index.core.embeddings import BaseEmbedding

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError


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


class EmbeddingModelFactory:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create(self):
        if self.settings.embedding_provider == "deterministic":
            return DeterministicEmbedding(
                model_name="deterministic-local",
                dimension=self.settings.embedding_dimension,
            )
        if self.settings.embedding_provider == "openai":
            if not self.settings.openai_api_key:
                raise ConfigurationError(
                    "OPENAI_API_KEY is required when EMBEDDING_PROVIDER=openai. "
                    "Use EMBEDDING_PROVIDER=deterministic only for explicit "
                    "local tests."
                )
            from llama_index.embeddings.openai import OpenAIEmbedding

            return OpenAIEmbedding(
                model=self.settings.embedding_model,
                api_key=self.settings.openai_api_key,
                api_base=self.settings.embedding_base_url,
                dimensions=self.settings.embedding_dimension,
                timeout=self.settings.llm_timeout_seconds,
            )
        raise ConfigurationError(
            f"unsupported embedding provider: {self.settings.embedding_provider!r}"
        )
