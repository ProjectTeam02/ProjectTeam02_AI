from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.retrieval.types import RetrievedDocument


@dataclass(slots=True)
class CitationValidationResult:
    valid: bool
    grounded: bool
    citations: list[RetrievedDocument]
    unsupported_references: list[str]


class CitationValidator:
    """Validate citation identity, not factual truth.

    Matching a document/chunk identifier proves only that the reference came from
    retrieved evidence. It does not replace human or model-based fact checking.
    """

    _citation_pattern = re.compile(
        r"(?:출처|source)\s*:\s*([^\]\s/]+)/([^\]\s]+)", re.IGNORECASE
    )

    def __init__(self, approved_status: str = "approved", min_overlap: float = 0.08):
        self.approved_status = approved_status
        self.min_overlap = min_overlap

    def validate(
        self, answer: str, sources: list[RetrievedDocument] | list[str]
    ) -> bool:
        if not answer.strip():
            return False
        if not sources:
            return False
        if all(isinstance(source, str) for source in sources):
            return all(source in answer for source in sources)
        result = self._result(answer, sources)  # type: ignore[arg-type]
        return result.valid and result.grounded

    def validate_and_build(
        self, answer: str, sources: list[RetrievedDocument]
    ) -> CitationValidationResult:
        return self._result(answer, sources)

    def _result(
        self, answer: str, sources: list[RetrievedDocument]
    ) -> CitationValidationResult:
        source_by_key = {source.citation_key(): source for source in sources}
        references = self._citation_pattern.findall(answer)
        unsupported = [
            f"{document_id}/{chunk_id}"
            for document_id, chunk_id in references
            if (document_id, chunk_id) not in source_by_key
        ]
        if unsupported:
            return CitationValidationResult(False, False, [], unsupported)

        referenced = [
            source_by_key[key]
            for key in {(doc_id, chunk_id) for doc_id, chunk_id in references}
        ]
        approved = [
            source
            for source in referenced
            if source.review_status == self.approved_status
        ]
        if not references or len(approved) != len(referenced):
            return CitationValidationResult(False, False, approved, [])
        grounded = self._has_claim_overlap(answer, approved)
        return CitationValidationResult(True, grounded, approved, [])

    def _has_claim_overlap(self, answer: str, sources: list[RetrievedDocument]) -> bool:
        answer_without_citations = self._citation_pattern.sub("", answer)
        answer_tokens = self._tokens(answer_without_citations)
        source_tokens = self._tokens(" ".join(source.content for source in sources))
        if not answer_tokens or not source_tokens:
            return False
        shared = answer_tokens & source_tokens
        overlap = len(shared) / len(answer_tokens)
        minimum_shared_terms = 1 if len(answer_tokens) <= 2 else 2
        return len(shared) >= minimum_shared_terms and overlap >= self.min_overlap

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return set(re.findall(r"[A-Za-z0-9]{2,}|[가-힣]{2,}", text.lower()))
