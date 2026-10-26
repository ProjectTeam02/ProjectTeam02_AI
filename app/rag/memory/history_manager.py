from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from app.core.exceptions import ConversationAccessError, ConversationNotFoundError
from app.rag.retrieval.types import RetrievedDocument


@dataclass(slots=True)
class HistoryMessage:
    role: str
    content: str
    created_at: datetime | None = None
    sequence_no: int | None = None


@dataclass(slots=True)
class ConversationHistory:
    conversation_id: str
    user_id: str
    messages: list[HistoryMessage] = field(default_factory=list)
    stage_id: str | None = None
    concept_id: str | None = None


@dataclass(slots=True)
class PersistedTurn:
    conversation_id: str
    answer: str
    citations: list[RetrievedDocument] = field(default_factory=list)
    grounded: bool = False


class InMemoryConversationRepository:
    """A process-local repository for tests and API smoke runs without a database."""

    def __init__(self) -> None:
        self._conversations: dict[str, ConversationHistory] = {}
        self._requests: dict[tuple[str, str], PersistedTurn] = {}
        self._lock = asyncio.Lock()

    async def create(
        self, user_id: str, stage_id: str | None = None, concept_id: str | None = None
    ) -> ConversationHistory:
        async with self._lock:
            conversation = ConversationHistory(
                str(uuid.uuid4()), user_id, stage_id=stage_id, concept_id=concept_id
            )
            self._conversations[conversation.conversation_id] = conversation
            return conversation

    async def get_owned(
        self, conversation_id: str, user_id: str
    ) -> ConversationHistory:
        conversation = self._conversations.get(conversation_id)
        if conversation is None:
            raise ConversationNotFoundError(conversation_id)
        if conversation.user_id != user_id:
            raise ConversationAccessError(conversation_id)
        return ConversationHistory(
            conversation.conversation_id,
            conversation.user_id,
            list(conversation.messages),
            conversation.stage_id,
            conversation.concept_id,
        )

    async def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        user_message: str,
        assistant_message: str,
        request_id: str | None = None,
        sources: list[RetrievedDocument] | None = None,
        grounded: bool = False,
    ) -> PersistedTurn:
        async with self._lock:
            if request_id and (user_id, request_id) in self._requests:
                return self._requests[(user_id, request_id)]
            conversation = self._conversations.get(conversation_id)
            if conversation is None:
                raise ConversationNotFoundError(conversation_id)
            if conversation.user_id != user_id:
                raise ConversationAccessError(conversation_id)
            # Both messages are added while holding one lock, preventing a
            # partially persisted turn.
            conversation.messages.extend(
                [
                    HistoryMessage("user", user_message),
                    HistoryMessage("assistant", assistant_message),
                ]
            )
            turn = PersistedTurn(
                conversation_id, assistant_message, list(sources or []), grounded
            )
            if request_id:
                self._requests[(user_id, request_id)] = turn
            return turn

    async def find_turn_by_request_id(
        self, user_id: str, request_id: str
    ) -> PersistedTurn | None:
        return self._requests.get((user_id, request_id))


class HistoryManager:
    def __init__(self, repository=None, max_messages: int = 12, max_tokens: int = 1200):
        self.repository = repository or InMemoryConversationRepository()
        self.max_messages = max(2, max_messages)
        self.max_tokens = max(100, max_tokens)

    async def create(
        self, user_id: str, stage_id: str | None = None, concept_id: str | None = None
    ) -> ConversationHistory:
        history = await self.repository.create(user_id, stage_id, concept_id)
        return self._history(history)

    async def load(self, conversation_id: str, user_id: str) -> ConversationHistory:
        history = await self.repository.get_owned(conversation_id, user_id)
        return self._history(history)

    async def append_turn(
        self,
        conversation_id: str,
        user_id: str,
        user_message: str,
        assistant_message: str,
        request_id: str | None = None,
        sources: list[RetrievedDocument] | None = None,
        grounded: bool = False,
    ) -> PersistedTurn:
        record = await self.repository.append_turn(
            conversation_id,
            user_id,
            user_message,
            assistant_message,
            request_id=request_id,
            sources=sources,
            grounded=grounded,
        )
        return self._turn(record)

    async def find_turn_by_request_id(
        self, user_id: str, request_id: str
    ) -> PersistedTurn | None:
        finder = getattr(self.repository, "find_turn_by_request_id", None)
        if finder is None:
            return None
        record = await finder(user_id, request_id)
        return self._turn(record) if record is not None else None

    def from_external(
        self,
        *,
        conversation_id: str,
        user_id: str,
        messages: list,
        summary: str | None = None,
        summary_until_seq: int | None = None,
        stage_id: str | None = None,
        concept_id: str | None = None,
    ) -> tuple[ConversationHistory, int | None]:
        """Build bounded history from the Node.js-owned conversation payload.

        Messages covered by ``summary_until_seq`` are excluded to avoid sending the
        same conversation content twice. No repository method is called here.
        """
        normalized: list[HistoryMessage] = []
        for item in messages:
            sequence_no = int(
                getattr(item, "sequence_no", None)
                if not isinstance(item, dict)
                else item.get("sequence_no", item.get("sequenceNo"))
            )
            if summary_until_seq is not None and sequence_no <= summary_until_seq:
                continue
            role = (
                getattr(item, "role", "unknown")
                if not isinstance(item, dict)
                else item.get("role", "unknown")
            )
            role_value = getattr(role, "value", role)
            content = (
                getattr(item, "content", "")
                if not isinstance(item, dict)
                else item.get("content", "")
            )
            normalized.append(
                HistoryMessage(
                    role=str(role_value).lower(),
                    content=str(content),
                    sequence_no=sequence_no,
                )
            )

        selected: list[HistoryMessage] = []
        token_count = 0
        summary_message: HistoryMessage | None = None
        if summary:
            summary_budget = max(1, self.max_tokens // 3)
            summary_text = summary[: summary_budget * 4]
            summary_message = HistoryMessage(
                role="summary",
                content=summary_text,
                sequence_no=summary_until_seq,
            )
            token_count = self._estimate_tokens(summary_text)

        for message in reversed(normalized[-self.max_messages :]):
            estimated = self._estimate_tokens(message.content)
            if selected and token_count + estimated > self.max_tokens:
                break
            if not selected and token_count + estimated > self.max_tokens:
                available = max(1, self.max_tokens - token_count)
                message = HistoryMessage(
                    role=message.role,
                    content=message.content[-available * 4 :],
                    sequence_no=message.sequence_no,
                )
                estimated = self._estimate_tokens(message.content)
            selected.append(message)
            token_count += estimated
        selected.reverse()
        if summary_message is not None:
            selected.insert(0, summary_message)

        history_from_seq = next(
            (
                message.sequence_no
                for message in selected
                if message.role != "summary" and message.sequence_no is not None
            ),
            None,
        )
        return (
            ConversationHistory(
                conversation_id=conversation_id,
                user_id=user_id,
                messages=selected,
                stage_id=stage_id,
                concept_id=concept_id,
            ),
            history_from_seq,
        )

    async def append(
        self, conversation_id: str, message: str, user_id: str | None = None
    ) -> None:
        """Compatibility helper; new code should use append_turn."""
        if user_id is None:
            raise ValueError(
                "user_id is required when appending a conversation message"
            )
        await self.repository.append_turn(conversation_id, user_id, message, "")

    def _history(self, history) -> ConversationHistory:
        selected: list[HistoryMessage] = []
        token_count = 0
        for item in reversed(history.messages[-self.max_messages :]):
            message = HistoryMessage(
                item.role,
                item.content,
                getattr(item, "created_at", None),
                getattr(item, "sequence_no", None),
            )
            estimated = self._estimate_tokens(message.content)
            if selected and token_count + estimated > self.max_tokens:
                break
            selected.append(message)
            token_count += estimated
        selected.reverse()
        return ConversationHistory(
            conversation_id=history.conversation_id
            if hasattr(history, "conversation_id")
            else history.id,
            user_id=history.user_id,
            messages=selected,
            stage_id=getattr(history, "stage_id", None),
            concept_id=getattr(history, "concept_id", None),
        )

    @staticmethod
    def _turn(record) -> PersistedTurn:
        citations = []
        for source in getattr(record, "citations", getattr(record, "sources", [])):
            if isinstance(source, RetrievedDocument):
                citations.append(source)
            else:
                citations.append(
                    RetrievedDocument(
                        content="",
                        source=source.source_url or "",
                        source_url=source.source_url,
                        source_id=source.source_id,
                        document_id=source.document_id,
                        chunk_id=source.chunk_id,
                        title=source.title,
                        version=source.document_version,
                    )
                )
        return PersistedTurn(
            record.conversation_id,
            record.answer,
            citations,
            getattr(record, "grounded", bool(citations)),
        )

    @staticmethod
    def _estimate_tokens(content: str) -> int:
        # Used only for bounding context. Provider-reported usage remains the
        # authoritative value returned by the internal API.
        return max(1, len(content) // 4)
