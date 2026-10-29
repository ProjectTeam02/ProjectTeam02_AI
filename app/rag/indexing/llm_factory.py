from __future__ import annotations

from app.core.config import Settings, get_settings
from app.core.exceptions import ConfigurationError

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


def _validate_model(provider: str, model: str, kind: str) -> None:
    if not model.strip():
        raise ConfigurationError(f"{kind} model must not be empty")
    # OpenRouter uses provider-qualified model IDs (for example,
    # ``openai/gpt-4o-mini``).  This is a local format check; availability is
    # still determined by the provider at request time.
    if provider == "openrouter" and "/" not in model:
        raise ConfigurationError(
            f"{kind} model for OpenRouter must be provider-qualified: {model!r}"
        )


def _api_key(settings: Settings, provider: str) -> str:
    if provider == "openrouter":
        key = settings.openrouter_api_key
        if not key:
            raise ConfigurationError(
                "OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter"
            )
        if not key.startswith("sk-or-v1-"):
            raise ConfigurationError(
                "OPENROUTER_API_KEY must start with 'sk-or-v1-'"
            )
        return key
    key = settings.openai_api_key
    if not key:
        raise ConfigurationError(
            "OPENAI_API_KEY is required when LLM_PROVIDER=openai"
        )
    return key


class OpenRouterLLM:
    """LlamaIndex OpenAI adapter with OpenRouter model-name compatibility.

    OpenRouter requires a provider-qualified model ID in the HTTP payload, but
    LlamaIndex uses its OpenAI-only model registry for metadata and token
    encoding.  The adapter preserves the qualified ``self.model`` for API
    requests while returning the unqualified suffix for those local lookups.
    """

    def __new__(cls, *args, **kwargs):
        from llama_index.llms.openai import OpenAI

        class _OpenRouterOpenAI(OpenAI):
            def _get_model_name(self) -> str:
                model_name = super()._get_model_name()
                return model_name.split("/", 1)[1] if "/" in model_name else model_name

        return _OpenRouterOpenAI(*args, **kwargs)


class LLMFactory:
    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def create(self):
        if self.settings.llm_provider in {"none", "offline"}:
            return None
        provider = self.settings.llm_provider
        if provider not in {"openai", "openrouter"}:
            raise ConfigurationError(
                f"unsupported LLM provider: {provider!r}"
            )
        _validate_model(provider, self.settings.llm_model, "LLM")
        api_key = _api_key(self.settings, provider)
        api_base = self.settings.llm_base_url
        if provider == "openrouter":
            api_base = api_base or OPENROUTER_BASE_URL

        llm_class = OpenRouterLLM if provider == "openrouter" else None
        if llm_class is None:
            from llama_index.llms.openai import OpenAI

            llm_class = OpenAI
        return llm_class(
            model=self.settings.llm_model,
            api_key=api_key,
            api_base=api_base,
            temperature=0.2,
            max_tokens=self.settings.llm_max_output_tokens,
            timeout=self.settings.llm_timeout_seconds,
        )
