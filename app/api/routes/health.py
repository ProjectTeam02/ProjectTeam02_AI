"""Compatibility import for the pre-v1 router path."""

from app.api.v1.routers.health import router

__all__ = ["router"]
