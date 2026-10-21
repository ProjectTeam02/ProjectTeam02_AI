from __future__ import annotations

import re
from dataclasses import dataclass

from app.rag.retrieval.types import RetrievedDocument


@dataclass(slots=True)
class CitationValidationResult:
    valid: bool
    citations: list[RetrievedDocument]
    unsupported_references: list[str]


class CitationValidator:
    """Validate citation identity, not factual truth.

    Matching a document/chunk identifier proves only that the reference came from
    retrieved evidence. It does not replace human or model-based fact checking.
    """

    _citation_pattern = re.compile(r"(?:출처|source)\s*:\s*([^\]\s/]+)/([^\]\s]+)", re.IGNORECASE)

    def validate(self, answer: str, sources: list[RetrievedDocument] | list[str]) -> bool:
        if not answer.strip():
            return False
        if not sources:
            return True
        if all(isinstance(source, str) for source in sources):
            return all(source in answer for source in sources)
        result = self._result(answer, sources)  # type: ignore[arg-type]
        return result.valid

    def validate_and_build(
        self, answer: str, sources: list[RetrievedDocument]
    ) -> CitationValidationResult:
        return self._result(answer, sources)

    def _result(self, answer: str, sources: list[RetrievedDocument]) -> CitationValidationResult:
        source_by_key = {source.citation_key(): source for source in sources}
        references = self._citation_pattern.findall(answer)
        unsupported = [f"{document_id}/{chunk_id}" for document_id, chunk_id in references if (document_id, chunk_id) not in source_by_key]
        if unsupported:
            return CitationValidationResult(False, [], unsupported)

        # If the model emitted no explicit markers, return only retrieved sources.
        # They are valid evidence candidates, never fabricated citations.
        referenced = [source_by_key[key] for key in {(doc_id, chunk_id) for doc_id, chunk_id in references}]
        return CitationValidationResult(True, referenced or list(sources), [])
