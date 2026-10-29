"""Compatibility import for the pre-v1 router path."""

from app.api.v1.routers.memory import list_memories, router

__all__ = ["router", "list_memories"]
