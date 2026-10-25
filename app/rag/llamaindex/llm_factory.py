from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError


class LLMFactory:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create(self):
        if self.settings.llm_provider in {"none", "offline"}:
            return None
        if self.settings.llm_provider != "openai":
            raise ConfigurationError(
                f"unsupported LLM provider: {self.settings.llm_provider!r}"
            )
        if not self.settings.openai_api_key:
            return None
        from llama_index.llms.openai import OpenAI

        return OpenAI(
            model=self.settings.llm_model,
            api_key=self.settings.openai_api_key,
            api_base=self.settings.llm_base_url,
            temperature=0.2,
            max_tokens=self.settings.llm_max_output_tokens,
            timeout=self.settings.llm_timeout_seconds,
        )
