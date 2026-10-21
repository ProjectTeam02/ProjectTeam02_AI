from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.core.exceptions import ConversationAccessError, ConversationNotFoundError


@dataclass(slots=True)
class HistoryMessage:
    role: str
    content: str
    created_at: datetime | None = None


@dataclass(slots=True)
class ConversationHistory:
    conversation_id: str
    user_id: str
    messages: list[HistoryMessage] = field(default_factory=list)


class InMemoryConversationRepository:
    """A process-local repository for tests and API smoke runs without a database."""

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationHistory] = {}
        self._lock = asyncio.Lock()

    async def create(self, user_id: str) -> ConversationHistory:
        async with self._lock:
            conversation = ConversationHistory(str(uuid.uuid4()), user_id)
            self._conversations[conversation.conversation_id] = conversation
            return conversation

    async def get_owned(self, conversation_id: str, user_id: str) -> ConversationHistory:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        if conversation.user_id != user_id:
            raise ConversationAccessError(conversation_id)
        return ConversationHistory(conversation.conversation_id, conversation.user_id, list(conversation.messages))

    async def append_turn(
        self, conversation_id: str, user_id: str, user_message: str, assistant_message: str
    ) -> None:
        async with self._lock:
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            if conversation.user_id != user_id:
                raise ConversationAccessError(conversation_id)
            # Both messages are added while holding one lock. There is no partially persisted turn.
            conversation.messages.extend(
                [HistoryMessage("user", user_message), HistoryMessage("assistant", assistant_message)]
            )


class HistoryManager:
    def __init__(self, repository=None, max_messages: int = 12):
        self.repository = repository or InMemoryConversationRepository()
        self.max_messages = max(2, max_messages)

    async def create(self, user_id: str) -> ConversationHistory:
        return await self.repository.create(user_id)

    async def load(self, conversation_id: str, user_id: str) -> ConversationHistory:
        history = await self.repository.get_owned(conversation_id, user_id)
        return ConversationHistory(
            conversation_id=history.conversation_id,
            user_id=history.user_id,
            messages=history.messages[-self.max_messages :],
        )

    async def append_turn(
        self, conversation_id: str, user_id: str, user_message: str, assistant_message: str
    ) -> None:
        await self.repository.append_turn(conversation_id, user_id, user_message, assistant_message)

    async def append(self, conversation_id: str, message: str, user_id: str | None = None) -> None:
        """Backward-compatible single-message helper; new code should use append_turn."""
        if user_id is None:
            raise ValueError("user_id is required when appending a conversation message")
        await self.repository.append_turn(conversation_id, user_id, message, "")
