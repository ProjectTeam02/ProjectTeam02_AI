from __future__ import annotations

import re
from dataclasses import replace

from app.rag.retrieval.types import RetrievedDocument


class LexicalReranker:
    """Dependency-free reranker for controlled comparisons.

    This is deliberately not presented as a cross-encoder. It provides a
    deterministic reranking arm for offline evaluation until a licensed,
    Korean-capable cross-encoder is approved for the runtime image.
    """

    @staticmethod
    def rerank(
        query: str, documents: list[RetrievedDocument]
    ) -> list[RetrievedDocument]:
        query_tokens = _tokens(query)
        scored: list[tuple[float, int, RetrievedDocument]] = []
        for index, document in enumerate(documents):
            content_tokens = _tokens(
                f"{document.title or ''} {document.content}"
            )
            overlap = len(query_tokens & content_tokens) / max(len(query_tokens), 1)
            original = document.score or 0.0
            score = 0.7 * overlap + 0.3 * original
            scored.append((score, index, replace(document, score=min(score, 1.0))))
        scored.sort(key=lambda item: (-item[0], item[1]))
        return [document for _, _, document in scored]


def _tokens(text: str) -> set[str]:
    return set(re.findall(r"[A-Za-z0-9]{2,}|[가-힣]{2,}", text.casefold()))
