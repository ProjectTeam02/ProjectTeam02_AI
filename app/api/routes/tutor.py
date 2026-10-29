"""Compatibility import for the pre-v1 router path."""

from app.api.v1.routers.tutor import chat, internal_answer, internal_router, router

__all__ = ["chat", "internal_answer", "internal_router", "router"]
