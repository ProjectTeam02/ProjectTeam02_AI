from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from app.schemas.question_generation import (
    EvidenceSource,
    ExistingQuestion,
    GenerationRequest,
)


class EvidenceProvider(Protocol):
    async def search(self, request: GenerationRequest) -> list[EvidenceSource]: ...


class ExistingQuestionProvider(Protocol):
    async def list_similar(
        self, request: GenerationRequest
    ) -> list[ExistingQuestion]: ...


class EmptyEvidenceProvider:
    """Fail-closed provider used until a repository is wired into the app."""

    async def search(self, request: GenerationRequest) -> list[EvidenceSource]:
        return []


class EmptyExistingQuestionProvider:
    async def list_similar(
        self, request: GenerationRequest
    ) -> list[ExistingQuestion]:
        return []


class JsonlEvidenceProvider:
    """Small local adapter for an approved KDI/BOK evidence JSONL file.

    Production retrieval can replace this adapter with the pgvector retriever
    without changing the generation pipeline.  Records are always filtered by
    ``review_status == approved`` here as a second safety boundary.
    """

    def __init__(self, path: str | Path | None, *, max_results: int = 12) -> None:
        self.path = Path(path) if path else None
        self.max_results = max_results

    async def search(self, request: GenerationRequest) -> list[EvidenceSource]:
        if self.path is None or not self.path.exists():
            return []

        query_terms = _terms(" ".join([request.topic, *request.learning_objectives]))
        candidates: list[tuple[int, EvidenceSource]] = []
        for raw in _read_jsonl(self.path):
            source = _to_evidence(raw)
            if source is None or source.review_status.casefold() != "approved":
                continue
            searchable = _terms(
                " ".join(
                    [
                        source.content,
                        source.source_id,
                        source.document_id,
                        source.publisher or "",
                    ]
                )
            )
            score = sum(
                any(term in candidate or candidate in term for candidate in searchable)
                for term in query_terms
            )
            if score:
                candidates.append((score, source))

        candidates.sort(key=lambda item: item[0], reverse=True)
        return [source for _, source in candidates[: self.max_results]]


class JsonlExistingQuestionProvider:
    def __init__(self, path: str | Path | None, *, max_results: int = 50) -> None:
        self.path = Path(path) if path else None
        self.max_results = max_results

    async def list_similar(
        self, request: GenerationRequest
    ) -> list[ExistingQuestion]:
        if self.path is None or not self.path.exists():
            return []

        query_terms = _terms(" ".join([request.topic, *request.learning_objectives]))
        candidates: list[tuple[int, ExistingQuestion]] = []
        for raw in _read_jsonl(self.path):
            try:
                question = ExistingQuestion.model_validate(raw)
            except Exception:
                continue
            score = len(query_terms & _terms(question.question))
            if score:
                candidates.append((score, question))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return [question for _, question in candidates[: self.max_results]]


def _read_jsonl(path: Path) -> Iterable[dict[str, object]]:
    try:
        with path.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    yield value
    except OSError:
        return


def _to_evidence(raw: dict[str, object]) -> EvidenceSource | None:
    metadata = raw.get("metadata")
    nested = metadata if isinstance(metadata, dict) else {}
    review_status = raw.get(
        "review_status",
        raw.get(
            "source_review_status",
            raw.get("reviewStatus", nested.get("review_status")),
        ),
    )
    source_id = raw.get(
        "source_id",
        raw.get("sourceId", nested.get("source_id", raw.get("source"))),
    )
    document_id = raw.get(
        "document_id", raw.get("documentId", raw.get("id", nested.get("document_id")))
    )
    document_version = raw.get(
        "document_version",
        raw.get(
            "documentVersion",
            raw.get("version", raw.get("dataset_version", nested.get("edition"))),
        ),
    )
    content = raw.get(
        "content", raw.get("text", raw.get("definition", nested.get("content")))
    )
    if not all(
        isinstance(value, str)
        for value in (source_id, document_id, document_version, content)
    ):
        return None
    try:
        return EvidenceSource(
            source_id=source_id,
            document_id=document_id,
            document_version=document_version,
            content=content,
            review_status=str(review_status or ""),
            publisher=_optional_string(raw.get("publisher", nested.get("publisher"))),
        )
    except Exception:
        return None


def _optional_string(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _terms(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[\w가-힣]+", value)
        if len(token.strip()) >= 2
    }
