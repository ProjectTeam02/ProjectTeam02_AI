from collections.abc import AsyncGenerator

from app.core.config import Settings, get_settings


def settings() -> Settings:
    return get_settings()


async def get_current_user_id() -> AsyncGenerator[str, None]:
    # TODO: replace with JWT validation.
    yield "development-user"
