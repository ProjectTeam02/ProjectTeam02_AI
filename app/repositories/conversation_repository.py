from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConversationAccessError, ConversationNotFoundError
from app.db.models import AIConversation, AIMessage, AIMessageSource


@dataclass(slots=True)
class MessageRecord:
    id: str
    role: str
    content: str
    created_at: datetime | None
    sequence_no: int = 0
    request_id: str | None = None


@dataclass(slots=True)
class ConversationRecord:
    id: str
    user_id: str
    messages: list[MessageRecord]
    created_at: datetime | None
    stage_id: str | None = None
    concept_id: str | None = None


@dataclass(slots=True)
class SourceRecord:
    source_id: str
    document_id: str
    chunk_id: str
    document_version: str | None
    title: str | None
    source_url: str | None


@dataclass(slots=True)
class TurnRecord:
    conversation_id: str
    answer: str
    sources: list[SourceRecord]
    grounded: bool = False


class ConversationRepository:
    """Transaction boundary for conversations and their messages."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self, user_id: str, stage_id: str | None = None, concept_id: str | None = None
    ) -> ConversationRecord:
        conversation = AIConversation(
            user_id=user_id, stage_id=stage_id, concept_id=concept_id
        )
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
            select(AIConversation).where(AIConversation.id == conversation_uuid)
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        if conversation.user_id != user_id:
            raise ConversationAccessError(conversation_id)

        messages_result = await self.session.execute(
            select(AIMessage)
            .where(AIMessage.conversation_id == conversation_uuid)
            .order_by(AIMessage.sequence_no, AIMessage.created_at, AIMessage.id)
        )
        return self._record(
            conversation, [self._message(item) for item in messages_result.scalars()]
        )

    async def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        user_message: str,
        assistant_message: str,
        request_id: str | None = None,
        sources: list | None = None,
        grounded: bool = False,
    ) -> TurnRecord:
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
            if request_id:
                existing = await self._find_turn(user_id, request_id, conversation_uuid)
                if existing is not None:
                    await self.session.rollback()
                    return existing
            sequence_result = await self.session.execute(
                select(func.coalesce(func.max(AIMessage.sequence_no), 0)).where(
                    AIMessage.conversation_id == conversation_uuid
                )
            )
            sequence_no = int(sequence_result.scalar_one())
            user_row = AIMessage(
                conversation_id=conversation_uuid,
                sequence_no=sequence_no + 1,
                role="user",
                content=user_message,
                request_id=request_id,
            )
            assistant_row = AIMessage(
                conversation_id=conversation_uuid,
                sequence_no=sequence_no + 2,
                role="assistant",
                content=assistant_message,
                request_id=request_id,
                grounded=grounded,
            )
            self.session.add_all([user_row, assistant_row])
            await self.session.flush()
            for source in sources or []:
                self.session.add(
                    AIMessageSource(
                        message_id=assistant_row.id,
                        source_id=str(source.source_id or source.document_id),
                        document_id=source.document_id,
                        chunk_id=source.chunk_id,
                        document_version=source.version,
                        title_snapshot=source.title,
                        source_url=source.source_url or source.source,
                    )
                )
            conversation.updated_at = func.now()
            await self.session.commit()
            return TurnRecord(
                conversation_id=conversation_id,
                answer=assistant_message,
                sources=[
                    SourceRecord(
                        source_id=str(item.source_id or item.document_id),
                        document_id=item.document_id,
                        chunk_id=item.chunk_id,
                        document_version=item.version,
                        title=item.title,
                        source_url=item.source_url or item.source,
                    )
                    for item in sources or []
                ],
                grounded=grounded,
            )
        except IntegrityError:
            await self.session.rollback()
            if request_id:
                existing = await self.find_turn_by_request_id(user_id, request_id)
                if existing is not None:
                    return existing
            raise
        except Exception:
            await self.session.rollback()
            raise

    async def find_turn_by_request_id(
        self, user_id: str, request_id: str
    ) -> TurnRecord | None:
        return await self._find_turn(user_id, request_id)

    async def _find_turn(
        self,
        user_id: str,
        request_id: str,
        conversation_id: uuid.UUID | None = None,
    ) -> TurnRecord | None:
        query = (
            select(AIMessage)
            .join(AIConversation, AIConversation.id == AIMessage.conversation_id)
            .where(
                AIConversation.user_id == user_id,
                AIMessage.request_id == request_id,
                AIMessage.role == "assistant",
                AIMessage.status == "completed",
            )
        )
        if conversation_id is not None:
            query = query.where(AIMessage.conversation_id == conversation_id)
        result = await self.session.execute(
            query.order_by(AIMessage.created_at.desc()).limit(1)
        )
        assistant = result.scalar_one_or_none()
        if assistant is None:
            return None
        sources_result = await self.session.execute(
            select(AIMessageSource).where(AIMessageSource.message_id == assistant.id)
        )
        return TurnRecord(
            conversation_id=str(assistant.conversation_id),
            answer=assistant.content,
            sources=[
                self._source_record(item) for item in sources_result.scalars().all()
            ],
            grounded=assistant.grounded,
        )

    @staticmethod
    def _message(message: AIMessage) -> MessageRecord:
        return MessageRecord(
            str(message.id),
            message.role,
            message.content,
            message.created_at,
            message.sequence_no,
            message.request_id,
        )

    @staticmethod
    def _source_record(source: AIMessageSource) -> SourceRecord:
        return SourceRecord(
            source_id=source.source_id,
            document_id=source.document_id,
            chunk_id=source.chunk_id,
            document_version=source.document_version,
            title=source.title_snapshot,
            source_url=source.source_url,
        )

    @staticmethod
    def _record(
        conversation: AIConversation, messages: list[MessageRecord]
    ) -> ConversationRecord:
        return ConversationRecord(
            str(conversation.id),
            conversation.user_id,
            messages,
            conversation.created_at,
            conversation.stage_id,
            conversation.concept_id,
        )
