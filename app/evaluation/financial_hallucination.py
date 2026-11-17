from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from app.rag.grounding.citation_validator import CitationValidator
from app.rag.retrieval.types import RetrievedDocument


class FinancialFindingType(StrEnum):
    UNSUPPORTED_CLAIM = "UNSUPPORTED_CLAIM"
    UNSUPPORTED_NUMERIC_CLAIM = "UNSUPPORTED_NUMERIC_CLAIM"
    CONTRADICTORY_HISTORY = "CONTRADICTORY_HISTORY"
    TERM_REQUIRES_HUMAN_REVIEW = "TERM_REQUIRES_HUMAN_REVIEW"
    UNDER_REFUSAL = "UNDER_REFUSAL"
    OVER_REFUSAL = "OVER_REFUSAL"


@dataclass(frozen=True, slots=True)
class FinancialFinding:
    finding_type: FinancialFindingType
    severity: str
    detail: str
    automatic: bool = True


@dataclass(slots=True)
class FinancialEvaluation:
    answerable: bool | None
    findings: list[FinancialFinding] = field(default_factory=list)
    human_review: dict[str, object] | None = None

    @property
    def hallucination_detected(self) -> bool:
        return any(
            finding.finding_type
            in {
                FinancialFindingType.UNSUPPORTED_CLAIM,
                FinancialFindingType.UNSUPPORTED_NUMERIC_CLAIM,
                FinancialFindingType.CONTRADICTORY_HISTORY,
                FinancialFindingType.UNDER_REFUSAL,
            }
            for finding in self.findings
        )


class FinancialHallucinationEvaluator:
    """Deterministic screening aligned with answerability-first evaluation.

    This is a screening layer, not a substitute for Korean financial expert
    review. Terminology correctness and subtle contradictions are explicitly
    marked for human review instead of being guessed by a heuristic.
    """

    _number_pattern = re.compile(
        r"(?<![A-Za-z가-힣])[-+]?\d+(?:[.,]\d+)?\s*(?:%|퍼센트|원|억|만|조)?"
    )
    _refusal_markers = ("확인하기 어려", "알 수 없", "답변할 수 없", "자료가 없어")

    def __init__(self, validator: CitationValidator | None = None):
        self.validator = validator or CitationValidator()

    def evaluate(
        self,
        *,
        answer: str,
        sources: list[RetrievedDocument],
        history: list[str] | None = None,
        answerable: bool | None = None,
        human_review: dict[str, object] | None = None,
    ) -> FinancialEvaluation:
        result = FinancialEvaluation(answerable=answerable, human_review=human_review)
        citation_result = self.validator.validate_and_build(answer, sources)
        if sources and not citation_result.valid:
            result.findings.append(
                FinancialFinding(
                    FinancialFindingType.UNSUPPORTED_CLAIM,
                    "high",
                    "citation identity does not match retrieved evidence",
                )
            )
        source_text = " ".join(source.content for source in sources)
        answer_numbers = set(self._number_pattern.findall(answer))
        source_numbers = set(self._number_pattern.findall(source_text))
        unsupported_numbers = sorted(answer_numbers - source_numbers)
        if unsupported_numbers:
            result.findings.append(
                FinancialFinding(
                    FinancialFindingType.UNSUPPORTED_NUMERIC_CLAIM,
                    "high",
                    "numeric claims absent from evidence: "
                    + ", ".join(unsupported_numbers),
                )
            )
        if history and self._contradicts_history(answer, history):
            result.findings.append(
                FinancialFinding(
                    FinancialFindingType.CONTRADICTORY_HISTORY,
                    "high",
                    "answer contains a numeric value that conflicts with prior turns",
                )
            )
        refused = self._is_refusal(answer)
        if answerable is True and refused:
            result.findings.append(
                FinancialFinding(
                    FinancialFindingType.OVER_REFUSAL,
                    "medium",
                    "answerable case was refused",
                )
            )
        if answerable is False and not refused:
            result.findings.append(
                FinancialFinding(
                    FinancialFindingType.UNDER_REFUSAL,
                    "high",
                    "unanswerable case was answered without abstention",
                )
            )
        result.findings.append(
            FinancialFinding(
                FinancialFindingType.TERM_REQUIRES_HUMAN_REVIEW,
                "review",
                (
                    "financial terminology and subtle factual consistency "
                    "require expert review"
                ),
                automatic=False,
            )
        )
        return result

    @classmethod
    def _is_refusal(cls, answer: str) -> bool:
        normalized = answer.casefold()
        return any(marker in normalized for marker in cls._refusal_markers)

    @classmethod
    def _contradicts_history(cls, answer: str, history: list[str]) -> bool:
        previous_numbers = set(
            number
            for item in history
            for number in cls._number_pattern.findall(item)
        )
        current_numbers = set(cls._number_pattern.findall(answer))
        return bool(
            previous_numbers
            and current_numbers
            and not current_numbers & previous_numbers
        )
