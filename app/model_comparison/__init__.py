"""Offline-first model comparison utilities for the Leren tutor."""

from app.model_comparison.catalog import MODEL_SPECS, ModelSpec
from app.model_comparison.contracts import ComparisonCase, ComparisonResult
from app.model_comparison.runner import ModelComparisonRunner

__all__ = [
    "MODEL_SPECS",
    "ComparisonCase",
    "ComparisonResult",
    "ModelComparisonRunner",
    "ModelSpec",
]
