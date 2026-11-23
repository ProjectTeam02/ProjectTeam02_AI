"""Small LlamaIndex-compatible LLM fallback used by the tutor only."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)


class FallbackLLM:
    """Try a primary model and then one fallback without changing API DTOs.

    The wrapper intentionally logs only model identifiers and exception types;
    prompts, responses, credentials, and provider payloads are never logged.
    """

    def __init__(
        self,
        primary,
        fallback=None,
        *,
        primary_model_id: str,
        fallback_model_id: str | None = None,
        attempt_timeout_seconds: float | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.primary_model_id = primary_model_id
        self.fallback_model_id = fallback_model_id
        self.attempt_timeout_seconds = attempt_timeout_seconds
        self.last_model_id = primary_model_id

    @property
    def model_id(self) -> str:
        return self.last_model_id

    async def _complete_one(self, llm, prompt: str):
        operation = llm.acomplete(prompt)
        if self.attempt_timeout_seconds is None:
            return await operation
        return await asyncio.wait_for(operation, self.attempt_timeout_seconds)

    async def acomplete(self, prompt: str):
        try:
            response = await self._complete_one(self.primary, prompt)
            self.last_model_id = self.primary_model_id
            return response
        except Exception as primary_error:
            if self.fallback is None:
                raise
            logger.warning(
                "tutor_model_fallback",
                extra={
                    "primary_model_id": self.primary_model_id,
                    "fallback_model_id": self.fallback_model_id,
                    "error_type": type(primary_error).__name__,
                },
            )
            try:
                response = await self._complete_one(self.fallback, prompt)
            except Exception:
                # Preserve the fallback exception for the existing generation
                # error mapping and avoid exposing provider details.
                raise
            self.last_model_id = self.fallback_model_id or "fallback"
            return response
