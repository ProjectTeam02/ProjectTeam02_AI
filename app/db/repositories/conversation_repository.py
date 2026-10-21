from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConversationAccessError, ConversationNotFoundError
from app.db.models import AIConversation, AIMessage


@dataclass(slots=True)
class MessageRecord:
    id: str
    role: str
    content: str
    created_at: datetime | None


@dataclass(slots=True)
class ConversationRecord:
    id: str
    user_id: str
    messages: list[MessageRecord]
    created_at: datetime | None


class ConversationRepository:
    """Transaction boundary for conversations and their messages."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, user_id: str) -> ConversationRecord:
        conversation = AIConversation(user_id=user_id)
        self.session.add(conversation)
        await self.session.commit()
        await self.session.refresh(conversation)
        return self._record(conversation, [])

    async def get_owned(self, conversation_id: str, user_id: str) -> ConversationRecord:
        try:
            conversation_uuid = uuid.UUID(conversation_id)
        except ValueError as exc:
            raise ConversationNotFoundError(conversation_id) from exc

        result = await self.session.execute(
            select(AIConversation)
            .where(AIConversation.id == conversation_uuid)
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        if conversation.user_id != user_id:
            raise ConversationAccessError(conversation_id)

        messages_result = await self.session.execute(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation_uuid)
            .order_by(AIMessage.created_at, AIMessage.id)
        )
        return self._record(conversation, [self._message(item) for item in messages_result.scalars()])

    async def append_turn(
        self, conversation_id: str, user_id: str, user_message: str, assistant_message: str
    ) -> None:
        try:
            conversation_uuid = uuid.UUID(conversation_id)
        except ValueError as exc:
            raise ConversationNotFoundError(conversation_id) from exc

        try:
            result = await self.session.execute(
                select(AIConversation)
                .where(AIConversation.id == conversation_uuid)
                .with_for_update()
            )
            conversation = result.scalar_one_or_none()
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            if conversation.user_id != user_id:
                raise ConversationAccessError(conversation_id)
            self.session.add_all(
                [
                    AIMessage(conversation_id=conversation_uuid, role="user", content=user_message),
                    AIMessage(conversation_id=conversation_uuid, role="assistant", content=assistant_message),
                ]
            )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise

    @staticmethod
    def _message(message: AIMessage) -> MessageRecord:
        return MessageRecord(str(message.id), message.role, message.content, message.created_at)

    @staticmethod
    def _record(
        conversation: AIConversation, messages: list[MessageRecord]
    ) -> ConversationRecord:
        return ConversationRecord(str(conversation.id), conversation.user_id, messages, conversation.created_at)
