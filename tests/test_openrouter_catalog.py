from __future__ import annotations

import httpx
import pytest

from app.model_comparison.openrouter_catalog import OpenRouterCatalogClient


@pytest.mark.asyncio
async def test_catalog_fetch_records_model_and_provider_metadata():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/models":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "provider/model",
                            "name": "Example Model",
                            "context_length": 128000,
                            "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                            "supported_parameters": [
                                "max_tokens",
                                "response_format",
                                "structured_outputs",
                            ],
                            "endpoints": ["/api/v1/chat/completions"],
                        }
                    ]
                },
            )
        if request.url.path == "/api/v1/models/provider/model/endpoints":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "endpoints": [
                            {
                                "provider_name": "Example Provider",
                                "tag": "standard",
                                "status": 200,
                                "context_length": 128000,
                                "max_completion_tokens": 4096,
                                "pricing": {
                                    "prompt": "0.000001",
                                    "completion": "0.000002",
                                },
                                "supported_parameters": ["max_tokens"],
                            }
                        ]
                    }
                },
            )
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        base_url="https://openrouter.test/api/v1", transport=transport
    ) as client:
        result = await OpenRouterCatalogClient(client=client).fetch(
            ["provider/model", "missing/model"]
        )

    model = result["provider/model"]
    assert model.available
    assert model.context_window == 128000
    assert model.input_price_per_million == 1.0
    assert model.output_price_per_million == 2.0
    assert model.structured_output_supported
    assert model.providers[0].provider_name == "Example Provider"
    assert not result["missing/model"].available
    assert result["missing/model"].reason == "MODEL_NOT_IN_CATALOG"

