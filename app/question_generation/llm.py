from __future__ import annotations

import json
from typing import Any, Protocol

import httpx

from app.core.config import Settings


class JsonLLM(Protocol):
    async def complete_json(
        self, *, system_prompt: str, user_payload: dict[str, Any]
    ) -> dict[str, Any] | str: ...


class LLMConfigurationError(RuntimeError):
    pass


class LLMRequestError(RuntimeError):
    pass


class OpenAICompatibleJsonLLM:
    """OpenRouter/OpenAI-compatible chat completion client.

    It asks the provider for a JSON object but still returns the raw parsed
    object to the application, which performs the authoritative schema checks.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        configured_url = settings.llm_base_url
        if configured_url is None:
            configured_url = (
                "https://openrouter.ai/api/v1"
                if settings.llm_provider == "openrouter"
                else "https://api.openai.com/v1"
            )
        self.base_url = configured_url.rstrip("/")

    async def complete_json(
        self, *, system_prompt: str, user_payload: dict[str, Any]
    ) -> dict[str, Any] | str:
        if self.settings.llm_provider == "openrouter":
            api_key = self.settings.openrouter_api_key
        elif self.settings.llm_provider == "openai":
            api_key = self.settings.openai_api_key
        else:
            api_key = None
        if not api_key:
            raise LLMConfigurationError("LLM credentials are not configured")

        payload = {
            "model": self.settings.llm_model,
            "temperature": 0.2,
            "messages": [
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": json.dumps(
                        user_payload, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {api_key}"}
        if self.settings.llm_provider.casefold() == "openrouter":
            headers["HTTP-Referer"] = (
                "https://github.com/ProjectTeam02/ProjectTeam02_AI"
            )
            headers["X-Title"] = "Leren question generation"

        try:
            async with httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.settings.llm_timeout_seconds,
            ) as client:
                response = await client.post(
                    "/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMRequestError("LLM request failed") from exc

        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMRequestError("LLM response did not contain content") from exc
        if isinstance(content, dict):
            return content
        if not isinstance(content, str):
            raise LLMRequestError("LLM content was not JSON text")
        return content
