"""Input and output contracts for the model comparison batch."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from app.rag.retrieval.types import RetrievedDocument
from app.schemas.tutor import PersonalizedTutorContext


@dataclass(slots=True)
class ComparisonCase:
    case_id: str
    question: str
    corpus: list[RetrievedDocument]
    history: list[dict[str, Any]] = field(default_factory=list)
    learning_concept: str | None = None
    incorrect_answer: str | None = None
    stage_id: str | None = None
    concept_id: str | None = None
    concept_codes: list[str] | None = None
    personalized_context: PersonalizedTutorContext | None = None

    def __post_init__(self) -> None:
        normalized_history: list[dict[str, Any]] = []
        for index, item in enumerate(self.history, start=1):
            normalized = dict(item)
            normalized["sequence_no"] = int(
                normalized.get("sequence_no", normalized.get("sequenceNo", index))
            )
            normalized_history.append(normalized)
        self.history = normalized_history

    @classmethod
    def from_dict(
        cls, payload: dict[str, Any], line_number: int = 0
    ) -> "ComparisonCase":
        if not isinstance(payload, dict):
            raise ValueError(f"line {line_number}: case must be a JSON object")
        case_id = str(_first_value(payload, "case_id", "caseId") or "").strip()
        question = str(
            _first_value(payload, "question", "studentQuestion") or ""
        ).strip()
        if not case_id:
            raise ValueError(f"line {line_number}: case_id is required")
        if not question:
            raise ValueError(f"line {line_number}: question is required")

        raw_history = _first_value(
            payload, "history", "conversationHistory", default=[]
        )
        if not isinstance(raw_history, list):
            raise ValueError(f"line {line_number}: history must be a list")
        history: list[dict[str, Any]] = []
        for item in raw_history:
            if not isinstance(item, dict):
                raise ValueError(f"line {line_number}: history item must be an object")
            role = str(item.get("role", "")).strip().lower()
            content = str(item.get("content", "")).strip()
            if role not in {"user", "assistant", "summary"} or not content:
                raise ValueError(f"line {line_number}: history role/content is invalid")
            sequence_no = item.get("sequence_no", item.get("sequenceNo"))
            try:
                sequence_no = int(sequence_no or len(history) + 1)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"line {line_number}: history sequence number is invalid"
                ) from exc
            history.append(
                {"role": role, "content": content, "sequence_no": sequence_no}
            )

        raw_corpus = _first_value(payload, "corpus", "approvedEvidence", default=[])
        if not isinstance(raw_corpus, list):
            raise ValueError(f"line {line_number}: corpus must be a list")
        corpus = [_document_from_dict(document, line_number) for document in raw_corpus]
        personal = _first_value(payload, "personalized_context", "personalizedContext")
        personalized_context = (
            PersonalizedTutorContext.model_validate(personal)
            if personal is not None
            else None
        )
        concept_codes = _first_value(payload, "concept_codes", "conceptCodes")
        if concept_codes is not None:
            if not isinstance(concept_codes, list) or any(
                not isinstance(value, str) or not value.strip()
                for value in concept_codes
            ):
                raise ValueError(f"line {line_number}: concept_codes is invalid")
            concept_codes = [value.strip() for value in concept_codes]

        return cls(
            case_id=case_id,
            question=question,
            corpus=corpus,
            history=history,
            learning_concept=_optional_string(
                _first_value(payload, "learning_concept", "learningConcept")
            ),
            incorrect_answer=_optional_string(
                _first_value(payload, "incorrect_answer", "incorrectAnswer")
            ),
            stage_id=_optional_string(_first_value(payload, "stage_id", "stageId")),
            concept_id=_optional_string(
                _first_value(payload, "concept_id", "conceptId")
            ),
            concept_codes=concept_codes,
            personalized_context=personalized_context,
        )

    def fingerprint(self) -> str:
        """Return a stable, non-reversible identifier for the case input."""

        payload = {
            "case_id": self.case_id,
            "question": self.question,
            "history": self.history,
            "corpus": [
                {
                    "document_id": document.document_id,
                    "chunk_id": document.chunk_id,
                    "content": document.content,
                    "review_status": document.review_status,
                }
                for document in self.corpus
            ],
            "learning_concept": self.learning_concept,
            "incorrect_answer": self.incorrect_answer,
            "stage_id": self.stage_id,
            "concept_id": self.concept_id,
            "concept_codes": self.concept_codes,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        return hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class ComparisonResult:
    case_id: str
    model_id: str
    mode: str
    status: str
    latency_ms: int
    input_hash: str
    prompt_version: str
    answer: str | None = None
    rewritten_query: str | None = None
    grounding_status: str | None = None
    citations: list[dict[str, Any]] = field(default_factory=list)
    usage: dict[str, int | None] = field(default_factory=dict)
    estimated_cost_usd: float | None = None
    error_type: str | None = None
    error_code: str | None = None
    provider_status: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "case_id": self.case_id,
            "model_id": self.model_id,
            "mode": self.mode,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "input_hash": self.input_hash,
            "prompt_version": self.prompt_version,
            "answer": self.answer,
            "rewritten_query": self.rewritten_query,
            "grounding_status": self.grounding_status,
            "citations": self.citations,
            "usage": self.usage,
            "estimated_cost_usd": self.estimated_cost_usd,
            "error": (
                {
                    "type": self.error_type,
                    "code": self.error_code,
                    "provider_status": self.provider_status,
                }
                if self.error_type or self.error_code
                else None
            ),
        }


def _optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _first_value(payload: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    return default


def _document_from_dict(payload: Any, line_number: int) -> RetrievedDocument:
    if not isinstance(payload, dict):
        raise ValueError(f"line {line_number}: corpus item must be an object")
    document_id = _first_value(payload, "document_id", "documentId", "sourceId")
    chunk_id = _first_value(payload, "chunk_id", "chunkId")
    source = _first_value(payload, "source", "publisher")
    required = {
        "content": payload.get("content"),
        "source": source,
        "document_id": document_id,
        "chunk_id": chunk_id,
    }
    missing = [key for key, value in required.items() if not str(value or "").strip()]
    if missing:
        raise ValueError(
            f"line {line_number}: corpus item missing {', '.join(missing)}"
        )
    allowed = set(RetrievedDocument.__dataclass_fields__)
    values = {key: value for key, value in payload.items() if key in allowed}
    values["document_id"] = document_id
    values["chunk_id"] = chunk_id
    values["source"] = source
    values["review_status"] = _first_value(
        payload, "review_status", "sourceReviewStatus", default="approved"
    )
    values["license"] = _first_value(payload, "license", "licenseStatus")
    values["content_hash"] = _first_value(payload, "content_hash", "contentHash")
    values["content"] = str(values["content"])
    values["source"] = str(values["source"])
    values["document_id"] = str(values["document_id"])
    values["chunk_id"] = str(values["chunk_id"])
    return RetrievedDocument(**values)
