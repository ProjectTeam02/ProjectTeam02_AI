"""The fixed model catalog used by the tutor comparison experiment.

The IDs and capability metadata were checked against the OpenRouter catalog on
2026-11-22. Prices are catalog defaults in USD per one million tokens; actual
cost is only written when the provider reports token usage.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ModelSpec:
    model_id: str
    display_name: str
    comparison_role: str
    context_window: int
    supports_text: bool = True
    supports_multiturn: bool = True
    supports_tools: bool = True
    supports_structured_output: bool = True
    input_price_per_million: float | None = None
    output_price_per_million: float | None = None


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "google/gemini-3.1-flash-lite",
        "Gemini 3.1 Flash Lite",
        "저지연·저비용",
        1_000_000,
        input_price_per_million=0.25,
        output_price_per_million=1.50,
    ),
    ModelSpec(
        "google/gemini-3-flash-preview",
        "Gemini 3 Flash Preview",
        "멀티턴·추론",
        1_048_576,
        input_price_per_million=0.50,
        output_price_per_million=3.00,
    ),
    ModelSpec(
        "openai/gpt-5.4-mini",
        "GPT-5.4 Mini",
        "설명 정확성",
        400_000,
        input_price_per_million=0.75,
        output_price_per_million=4.50,
    ),
    ModelSpec(
        "qwen/qwen3.5-flash-02-23",
        "Qwen3.5 Flash",
        "비용 효율",
        1_000_000,
        input_price_per_million=0.065,
        output_price_per_million=0.26,
    ),
    ModelSpec(
        "anthropic/claude-haiku-4.5",
        "Claude Haiku 4.5",
        "교육적 설명 품질",
        200_000,
        input_price_per_million=1.00,
        output_price_per_million=5.00,
    ),
)

MODEL_BY_ID = {spec.model_id: spec for spec in MODEL_SPECS}


def select_models(model_ids: list[str] | None = None) -> tuple[ModelSpec, ...]:
    """Return the catalog order, optionally restricted to known model IDs."""

    if not model_ids:
        return MODEL_SPECS
    requested = [model_id.strip() for model_id in model_ids if model_id.strip()]
    unknown = sorted(set(requested) - MODEL_BY_ID.keys())
    if unknown:
        raise ValueError(f"unknown comparison model(s): {', '.join(unknown)}")
    return tuple(MODEL_BY_ID[model_id] for model_id in requested)
