from app.evaluation.financial_hallucination import (
    FinancialFindingType,
    FinancialHallucinationEvaluator,
)
from app.rag.retrieval.types import RetrievedDocument


def source() -> RetrievedDocument:
    return RetrievedDocument(
        content="기준금리는 3.5%이며 중앙은행의 정책금리입니다.",
        source="bok",
        document_id="DOC-1",
        chunk_id="DOC-1:1",
    )


def test_financial_evaluator_detects_unsupported_number_and_separates_review():
    result = FinancialHallucinationEvaluator().evaluate(
        answer="기준금리는 8%입니다. [출처: DOC-1/DOC-1:1]",
        sources=[source()],
        answerable=True,
    )

    types = {finding.finding_type for finding in result.findings}
    assert FinancialFindingType.UNSUPPORTED_NUMERIC_CLAIM in types
    assert FinancialFindingType.TERM_REQUIRES_HUMAN_REVIEW in types
    assert any(not finding.automatic for finding in result.findings)


def test_financial_evaluator_detects_under_and_over_refusal():
    evaluator = FinancialHallucinationEvaluator()
    under = evaluator.evaluate(
        answer="기준금리는 3.5%입니다.",
        sources=[],
        answerable=False,
    )
    over = evaluator.evaluate(
        answer="현재 자료가 없어 정확하게 설명하기 어려워요.",
        sources=[source()],
        answerable=True,
    )

    assert any(
        finding.finding_type == FinancialFindingType.UNDER_REFUSAL
        for finding in under.findings
    )
    assert any(
        finding.finding_type == FinancialFindingType.OVER_REFUSAL
        for finding in over.findings
    )
