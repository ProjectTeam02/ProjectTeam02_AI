# 파일 역할: HTTP API 계층의 의존성 또는 라우터를 정의합니다.
"""Compatibility import for the pre-v1 router path."""

from app.api.v1.routers.health import router

__all__ = ["router"]
