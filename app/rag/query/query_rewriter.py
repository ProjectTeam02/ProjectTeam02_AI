from __future__ import annotations

import asyncio
import re

from app.rag.memory.history_manager import ConversationHistory, HistoryMessage


class QueryRewriter:
    """Rewrite only context-dependent follow-up questions."""

    FOLLOW_UP_MARKERS = (
        "그건",
        "그게",
        "그것",
        "이건",
        "이게",
        "이것",
        "앞에서",
        "방금",
        "무슨 관계",
        "왜 그래",
    )
    LEADING_CONNECTORS = ("그럼", "그러면")
    GENERIC_FOLLOW_UP_WORDS = {
        "왜",
        "어떻게",
        "오르면",
        "내리면",
        "증가하면",
        "감소하면",
        "좋은",
        "나쁜",
        "거야",
        "돼",
    }

    def __init__(self, llm=None, timeout_seconds: float = 10.0):
        self.llm = llm
        self.timeout_seconds = timeout_seconds

    async def rewrite(
        self,
        message: str,
        history: ConversationHistory | list[HistoryMessage] | list[dict],
    ) -> str:
        messages = (
            history.messages if isinstance(history, ConversationHistory) else history
        )
        if not messages or not self._needs_rewrite(message):
            return message

        if self.llm is not None:
            try:
                response = await asyncio.wait_for(
                    self.llm.acomplete(self._prompt(message, messages)),
                    self.timeout_seconds,
                )
                text = getattr(response, "text", str(response)).strip()
                if text:
                    return text[:1000]
            except Exception:
                # Retrieval can safely continue with the original follow-up.
                pass
        return self._deterministic_rewrite(message, messages)

    def _needs_rewrite(self, message: str) -> bool:
        normalized = message.strip()
        if any(marker in normalized for marker in self.FOLLOW_UP_MARKERS):
            return True
        connector = next(
            (
                marker
                for marker in self.LEADING_CONNECTORS
                if normalized.startswith(marker)
            ),
            None,
        )
        if connector is None:
            return False
        remainder = normalized[len(connector) :]
        tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*|[가-힣]{2,}", remainder)
        explicit_topic = any(
            token not in self.GENERIC_FOLLOW_UP_WORDS for token in tokens
        )
        return not explicit_topic

    @staticmethod
    def _item_value(item: HistoryMessage | dict, key: str, default: str = "") -> str:
        if isinstance(item, dict):
            return str(item.get(key, default))
        return str(getattr(item, key, default))

    @classmethod
    def _prompt(cls, message: str, messages: list[HistoryMessage] | list[dict]) -> str:
        history_text = "\n".join(
            f"{cls._item_value(item, 'role', 'unknown')}: "
            f"{cls._item_value(item, 'content')}"
            for item in messages[-6:]
        )
        return (
            "이전 대화와 현재 질문을 바탕으로 검색용 독립 질문을 "
            "한 문장으로 작성하세요. "
            "새로운 의도나 사실을 추가하지 마세요. 질문만 출력하세요.\n"
            f"이전 대화:\n{history_text}\n현재 질문: {message}"
        )

    @classmethod
    def _deterministic_rewrite(
        cls, message: str, messages: list[HistoryMessage] | list[dict]
    ) -> str:
        previous_user_questions = [
            cls._item_value(item, "content")
            for item in messages
            if cls._item_value(item, "role") == "user"
        ]
        previous = previous_user_questions[-1] if previous_user_questions else ""
        topic_tokens = re.findall(r"[A-Za-z][A-Za-z0-9-]*|[가-힣]{2,}", previous)
        topic = " ".join(topic_tokens[:8]).strip()
        if not topic:
            return message
        return f"이전 대화의 주제({topic})와 관련하여 다음 질문에 답하라: {message}"
