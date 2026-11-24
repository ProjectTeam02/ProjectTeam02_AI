"""Read-only OpenRouter model and provider metadata for evaluations."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from typing import Any

import httpx

from app.rag.indexing.llm_factory import OPENROUTER_BASE_URL


class OpenRouterCatalogError(RuntimeError):
    """The OpenRouter catalog could not be read or was malformed."""


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    provider_name: str
    tag: str | None
    status: int | None
    context_length: int | None
    max_completion_tokens: int | None
    input_price_per_million: float | None
    output_price_per_million: float | None
    supported_parameters: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OpenRouterModelMetadata:
    model_id: str
    name: str | None
    available: bool
    reason: str | None
    context_window: int | None
    input_price_per_million: float | None
    output_price_per_million: float | None
    supported_parameters: tuple[str, ...]
    structured_output_supported: bool
    endpoints: tuple[str, ...]
    providers: tuple[ProviderMetadata, ...]
    fetched_at: str

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "providers": [provider.as_dict() for provider in self.providers],
        }


class OpenRouterCatalogClient:
    """Fetch model metadata without requiring an OpenRouter API key."""

    def __init__(
        self,
        *,
        base_url: str = OPENROUTER_BASE_URL,
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._client = client

    async def fetch(
        self,
        model_ids: list[str] | tuple[str, ...],
        *,
        include_providers: bool = True,
    ) -> dict[str, OpenRouterModelMetadata]:
        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
        )
        try:
            models = await self._get_models(client)
            results: dict[str, OpenRouterModelMetadata] = {}
            fetched_at = datetime.now(timezone.utc).isoformat()
            for model_id in model_ids:
                model = models.get(model_id)
                if model is None:
                    results[model_id] = _unavailable(
                        model_id, fetched_at, "MODEL_NOT_IN_CATALOG"
                    )
                    continue
                providers: tuple[ProviderMetadata, ...] = ()
                provider_error = None
                if include_providers:
                    try:
                        providers = _providers_from_payload(
                            await self._get_endpoints(client, model_id)
                        )
                    except (httpx.HTTPError, ValueError, KeyError) as exc:
                        provider_error = (
                            "PROVIDER_METADATA_UNAVAILABLE:"
                            f"{type(exc).__name__}"
                        )
                metadata = _model_metadata(model, fetched_at, providers)
                if provider_error:
                    metadata = replace(metadata, reason=provider_error)
                results[model_id] = metadata
            return results
        finally:
            if owns_client:
                await client.aclose()

    async def _get_models(self, client: httpx.AsyncClient) -> dict[str, dict[str, Any]]:
        response = await client.get("/models")
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise OpenRouterCatalogError("OpenRouter /models response is invalid")
        return {
            str(row.get("id")): row
            for row in rows
            if isinstance(row, dict) and str(row.get("id", "")).strip()
        }

    async def _get_endpoints(
        self, client: httpx.AsyncClient, model_id: str
    ) -> dict[str, Any]:
        response = await client.get(f"/models/{model_id}/endpoints")
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("OpenRouter endpoint response is invalid")
        return payload

    async def fetch_generation(self, generation_id: str) -> dict[str, Any] | None:
        """Fetch optional provider-side usage details for a generation ID."""

        owns_client = self._client is None
        client = self._client or httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self.timeout_seconds,
        )
        try:
            response = await client.get("/generation", params={"id": generation_id})
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        finally:
            if owns_client:
                await client.aclose()


def _model_metadata(
    model: dict[str, Any],
    fetched_at: str,
    providers: tuple[ProviderMetadata, ...],
) -> OpenRouterModelMetadata:
    parameters = tuple(sorted(_string_values(model.get("supported_parameters"))))
    endpoints = tuple(sorted(_string_values(model.get("endpoints"))))
    chat_available = "/api/v1/chat/completions" in endpoints
    reason = None if chat_available else "CHAT_COMPLETIONS_NOT_SUPPORTED"
    return OpenRouterModelMetadata(
        model_id=str(model["id"]),
        name=_optional_string(model.get("name")),
        available=chat_available,
        reason=reason,
        context_window=_int_value(model.get("context_length")),
        input_price_per_million=_price_per_million(
            model.get("pricing", {}).get("prompt")
        ),
        output_price_per_million=_price_per_million(
            model.get("pricing", {}).get("completion")
        ),
        supported_parameters=parameters,
        structured_output_supported=bool(
            {"structured_outputs", "response_format"} & set(parameters)
        ),
        endpoints=endpoints,
        providers=providers,
        fetched_at=fetched_at,
    )


def _providers_from_payload(payload: dict[str, Any]) -> tuple[ProviderMetadata, ...]:
    data = payload.get("data", payload)
    rows = data.get("endpoints", []) if isinstance(data, dict) else []
    if not isinstance(rows, list):
        raise ValueError("OpenRouter endpoint list is invalid")
    providers: list[ProviderMetadata] = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get("provider_name", "")).strip():
            continue
        parameters = tuple(sorted(_string_values(row.get("supported_parameters"))))
        providers.append(
            ProviderMetadata(
                provider_name=str(row["provider_name"]),
                tag=_optional_string(row.get("tag")),
                status=_int_value(row.get("status")),
                context_length=_int_value(row.get("context_length")),
                max_completion_tokens=_int_value(row.get("max_completion_tokens")),
                input_price_per_million=_price_per_million(
                    row.get("pricing", {}).get("prompt")
                ),
                output_price_per_million=_price_per_million(
                    row.get("pricing", {}).get("completion")
                ),
                supported_parameters=parameters,
            )
        )
    return tuple(providers)


def _unavailable(
    model_id: str, fetched_at: str, reason: str
) -> OpenRouterModelMetadata:
    return OpenRouterModelMetadata(
        model_id=model_id,
        name=None,
        available=False,
        reason=reason,
        context_window=None,
        input_price_per_million=None,
        output_price_per_million=None,
        supported_parameters=(),
        structured_output_supported=False,
        endpoints=(),
        providers=(),
        fetched_at=fetched_at,
    )


def _string_values(value: Any) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []


def _optional_string(value: Any) -> str | None:
    value = str(value).strip() if value is not None else ""
    return value or None


def _int_value(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _price_per_million(value: Any) -> float | None:
    try:
        return round(float(value) * 1_000_000, 12) if value is not None else None
    except (TypeError, ValueError):
        return None
