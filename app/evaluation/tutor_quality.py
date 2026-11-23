"""Human-review-first 60-point evaluation for Leren tutor answers."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.config import Settings, get_settings
from app.evaluation.financial_hallucination import (
    FinancialFindingType,
    FinancialHallucinationEvaluator,
)
from app.evaluation.tutor_dataset import (
    DIFFICULTY_COUNTS,
    REQUIRED_FIELDS,
    SCENARIO_TYPE_COUNTS,
)
from app.rag.grounding.citation_validator import CitationValidator
from app.rag.harness import ExecutionHarness, StageContract
from app.rag.indexing.llm_factory import LLMFactory
from app.rag.retrieval.types import RetrievedDocument

RUBRIC_VERSION = "tutor-education-60-v1"
JUDGE_PROMPT_VERSION = "tutor-quality-judge-v1"
DEFAULT_JUDGE_MODEL = "openai/gpt-5.4-mini"
APPROVED_LICENSE_STATUSES = {"approved", "cleared", "verified"}
SUCCESS_STATUSES = {"ok", "mock", "no_evidence"}

RUBRIC = (
    {
        "key": "accuracyScore",
        "name": "경제적 정확성",
        "max": 15,
        "criteria": "경제·금융 개념, 조건, 수치와 인과관계를 사실에 맞게 설명한다.",
        "levels": {
            "zero": "핵심 개념이나 수치가 틀리거나 위험한 인과를 단정한다.",
            "partial": "대체로 맞지만 조건·범위·예외의 작은 누락이 있다.",
            "full": "개념·조건·수치·인과와 한계를 모두 정확히 설명한다.",
        },
    },
    {
        "key": "groundingScore",
        "name": "RAG Grounding",
        "max": 10,
        "criteria": (
            "승인된 자료에 근거하고, 인용문과 출처 식별자가 실제 원문과 일치한다."
        ),
        "levels": {
            "zero": "승인 근거를 사용하지 않거나 존재하지 않는 인용을 만든다.",
            "partial": "근거는 대체로 맞지만 일부 주장 또는 인용의 계보가 불완전하다.",
            "full": "모든 핵심 주장이 승인 원문에 있고 인용문·ID가 일치한다.",
        },
    },
    {
        "key": "misconceptionScore",
        "name": "오개념 진단·교정",
        "max": 15,
        "criteria": "오개념을 단정하지 않고 확인 질문과 근거 기반 교정을 제공한다.",
        "levels": {
            "zero": "오개념을 오진단하거나 틀린 교정·비난을 한다.",
            "partial": "교정은 맞지만 진단 근거 또는 확인 질문이 부족하다.",
            "full": "가설로 유지하고 반복 증거를 확인한 뒤 맞춤 교정을 제공한다.",
        },
    },
    {
        "key": "personalizationScore",
        "name": "개인화·멀티턴",
        "max": 10,
        "criteria": (
            "학습자 신호와 이전 대화 맥락을 유지하되 과도한 진단이나 "
            "개인정보 노출을 피한다."
        ),
        "levels": {
            "zero": "이전 맥락·학습자 신호를 무시하거나 개인정보를 노출한다.",
            "partial": "맥락 또는 개인화는 반영하지만 일부 연결이 약하다.",
            "full": "맥락과 학습자 신호를 자연스럽게 반영하고 경계를 지킨다.",
        },
    },
    {
        "key": "pedagogyScore",
        "name": "교수 전략·이해도 확인",
        "max": 10,
        "criteria": "쉬운 설명, 적절한 예시, 단계적 안내와 이해도 확인을 제공한다.",
        "levels": {
            "zero": "설명이 불필요하게 복잡하고 이해도 확인이 없다.",
            "partial": "설명은 이해 가능하지만 예시·단계화·확인 중 일부가 부족하다.",
            "full": "학습자 수준에 맞는 단계적 설명과 확인 질문을 제공한다.",
        },
    },
)
RUBRIC_MAX_SCORE = sum(item["max"] for item in RUBRIC)

CRITICAL_ERROR_DEDUCTIONS = {
    "ECONOMIC_FACT_ERROR": 15,
    "UNSUPPORTED_EVIDENCE": 10,
    "CAUSAL_ERROR": 5,
    "MISCONCEPTION_MISDIAGNOSIS": 10,
    "CONTEXT_IGNORED": 5,
    "OVERCOMPLEX_EXPLANATION": 3,
    "UNDERSTANDING_CHECK_MISSING": 3,
    "PERSONAL_DATA_EXPOSURE": 10,
}
KNOWN_CRITICAL_ERRORS = set(CRITICAL_ERROR_DEDUCTIONS) | {
    "JUDGE_OUTPUT_INVALID",
    "JUDGE_CITATION_INVALID",
    "UNREVIEWED_GOLD",
    "MODEL_EXECUTION_ERROR",
}

_CITATION_PATTERN = re.compile(
    r"(?:출처|source)\s*:\s*([^\]\s/]+)/([^\]\s]+)", re.IGNORECASE
)
_EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
_PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d\s-]{7,}\d)(?!\d)")


class JudgeCitation(BaseModel):
    document_id: str = Field(alias="documentId", min_length=1)
    chunk_id: str = Field(alias="chunkId", min_length=1)
    quote: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


class JudgeDeduction(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    points: float = Field(ge=0.0, le=60.0)
    reason: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class JudgeCriticalError(BaseModel):
    code: str = Field(min_length=1, max_length=80)
    severity: str = Field(default="high", min_length=1, max_length=20)
    detail: str = Field(min_length=1, max_length=1000)

    model_config = ConfigDict(extra="forbid")


class JudgePayload(BaseModel):
    accuracy_score: float = Field(alias="accuracyScore", ge=0.0, le=15.0)
    grounding_score: float = Field(alias="groundingScore", ge=0.0, le=10.0)
    misconception_score: float = Field(alias="misconceptionScore", ge=0.0, le=15.0)
    personalization_score: float = Field(alias="personalizationScore", ge=0.0, le=10.0)
    pedagogy_score: float = Field(alias="pedagogyScore", ge=0.0, le=10.0)
    deductions: list[JudgeDeduction] = Field(default_factory=list)
    critical_errors: list[JudgeCriticalError] = Field(
        default_factory=list, alias="criticalErrors"
    )
    evidence_citations: list[JudgeCitation] = Field(
        default_factory=list, alias="evidenceCitations"
    )
    needs_human_review: bool = Field(alias="needsHumanReview")
    rationale: dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True, extra="forbid")


@dataclass(frozen=True, slots=True)
class JudgeResponse:
    text: str
    usage: dict[str, Any] | None = None


class JudgeClient(Protocol):
    model_id: str

    async def complete(self, prompt: str) -> JudgeResponse: ...


class MockJudgeClient:
    """Deterministic, offline Judge used by tests and the default CLI mode."""

    model_id = "mock/judge-v1"

    async def complete(self, prompt: str) -> JudgeResponse:
        answer = _extract_block(prompt, "CANDIDATE_ANSWER")
        evidence_text = _extract_block(prompt, "APPROVED_EVIDENCE")
        evidence = _parse_json_block(evidence_text) or []
        citations = []
        if evidence:
            first = evidence[0]
            content = str(first.get("content", "")).strip()
            citations.append(
                {
                    "documentId": first.get("documentId", first.get("sourceId")),
                    "chunkId": first.get("chunkId"),
                    "quote": content[: min(80, len(content))],
                }
            )
        is_bad = "[WRONG]" in answer or "항상" in answer or "무조건" in answer
        has_check = "?" in answer or "이해" in answer or "확인" in answer
        if is_bad:
            payload = {
                "accuracyScore": 2,
                "groundingScore": 1 if citations else 0,
                "misconceptionScore": 3,
                "personalizationScore": 2,
                "pedagogyScore": 3,
                "deductions": [],
                "criticalErrors": [
                    {
                        "code": "ECONOMIC_FACT_ERROR",
                        "severity": "critical",
                        "detail": "모의 Judge가 사실 단정 오류를 탐지함",
                    },
                    {
                        "code": "CAUSAL_ERROR",
                        "severity": "high",
                        "detail": "조건 없는 단방향 인과를 단정함",
                    },
                ],
                "evidenceCitations": citations,
                "needsHumanReview": True,
                "rationale": {"mock": "bad-answer fixture"},
            }
        else:
            payload = {
                "accuracyScore": 14,
                "groundingScore": 10 if citations else 4,
                "misconceptionScore": 14,
                "personalizationScore": 9,
                "pedagogyScore": 10 if has_check else 7,
                "deductions": [],
                "criticalErrors": [],
                "evidenceCitations": citations,
                "needsHumanReview": False,
                "rationale": {"mock": "deterministic normal-answer fixture"},
            }
        return JudgeResponse(
            text=json.dumps(payload, ensure_ascii=False),
            usage={"prompt_tokens": 256, "completion_tokens": 128},
        )


class OpenRouterJudgeClient:
    """OpenRouter Judge adapter; only constructed for an explicit live run."""

    def __init__(
        self,
        model_id: str,
        settings: Settings | None = None,
    ):
        self.model_id = model_id
        base_settings = settings or get_settings()
        judge_settings = base_settings.model_copy(
            update={"llm_provider": "openrouter", "llm_model": model_id}
        )
        self.settings = judge_settings
        self.llm = LLMFactory(judge_settings).create()
        self.harness = ExecutionHarness(
            timeout_seconds=judge_settings.llm_timeout_seconds,
            max_retries=0,
        )

    async def complete(self, prompt: str) -> JudgeResponse:
        response = await self.harness.run(
            StageContract(
                name="tutor_quality_judge",
                input_description="anonymous tutor answer and approved evidence",
                output_description="structured JSON Judge response",
            ),
            lambda: self.llm.acomplete(prompt),
            [],
        )
        raw = getattr(response, "raw", None)
        usage = getattr(raw, "usage", None)
        if hasattr(usage, "model_dump"):
            usage = usage.model_dump()
        elif not isinstance(usage, dict):
            usage = None
        return JudgeResponse(
            text=str(getattr(response, "text", response)).strip(),
            usage=usage,
        )


def tutor_quality_schema() -> dict[str, Any]:
    """Return the machine-readable schema used before Judge execution."""

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Leren tutor quality evaluation result",
        "type": "object",
        "required": [
            "caseId",
            "modelId",
            "evaluationStatus",
            "judgeModelId",
            "judgePromptVersion",
            "accuracyScore",
            "groundingScore",
            "misconceptionScore",
            "personalizationScore",
            "pedagogyScore",
            "totalEducationScore",
            "deductions",
            "criticalErrors",
            "needsHumanReview",
        ],
        "properties": {
            "caseId": {"type": "string"},
            "modelId": {"type": ["string", "null"]},
            "evaluationStatus": {"type": "string"},
            "judgeModelId": {"type": "string"},
            "judgePromptVersion": {"type": "string"},
            "accuracyScore": {"type": ["number", "null"], "minimum": 0},
            "groundingScore": {"type": ["number", "null"], "minimum": 0},
            "misconceptionScore": {
                "type": ["number", "null"],
                "minimum": 0,
            },
            "personalizationScore": {
                "type": ["number", "null"],
                "minimum": 0,
            },
            "pedagogyScore": {"type": ["number", "null"], "minimum": 0},
            "totalEducationScore": {
                "type": ["number", "null"],
                "minimum": 0,
                "maximum": RUBRIC_MAX_SCORE,
            },
            "deductions": {"type": "array"},
            "criticalErrors": {"type": "array"},
            "needsHumanReview": {"type": "boolean"},
        },
    }


def validate_tutor_case_schema(case: dict[str, Any]) -> list[str]:
    """Perform the first evaluation stage without inferring missing Gold data."""

    errors: list[str] = []
    missing = sorted(REQUIRED_FIELDS - set(case))
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")
    if not isinstance(case.get("sourceIds"), list) or not case.get("sourceIds"):
        errors.append("sourceIds must be a non-empty list")
    if case.get("difficulty") not in DIFFICULTY_COUNTS:
        errors.append("difficulty is invalid")
    if case.get("scenarioType") not in SCENARIO_TYPE_COUNTS:
        errors.append("scenarioType is invalid")
    if not isinstance(case.get("approvedEvidence"), list):
        errors.append("approvedEvidence must be a list")
    if not isinstance(case.get("conversationHistory"), list):
        errors.append("conversationHistory must be a list")
    if (
        not isinstance(case.get("studentQuestion"), str)
        or not case.get("studentQuestion", "").strip()
    ):
        errors.append("studentQuestion must be a non-empty string")
    return errors


def gold_gate(case: dict[str, Any]) -> tuple[bool, list[str]]:
    """Return whether this case may receive a final educational score."""

    reasons: list[str] = []
    if case.get("goldStatus") != "INDEPENDENT_APPROVED":
        reasons.append("goldStatus is not INDEPENDENT_APPROVED")
    if not case.get("conceptCode"):
        reasons.append("canonical conceptCode is missing")
    evidence = case.get("approvedEvidence", [])
    if not evidence:
        reasons.append("approvedEvidence is empty")
    for item in evidence:
        if item.get("approvalStatus") != "approved":
            reasons.append("evidence approvalStatus is not approved")
        if item.get("licenseStatus") not in APPROVED_LICENSE_STATUSES:
            reasons.append("evidence licenseStatus is not approved")
        if not str(item.get("content", "")).strip():
            reasons.append("approved evidence content is empty")
    return not reasons, sorted(set(reasons))


def build_judge_prompt(
    case: dict[str, Any],
    comparison_result: dict[str, Any],
    *,
    anonymous_response_id: str,
) -> str:
    """Build one fixed Judge prompt; target model identity is intentionally absent."""

    public_case = {
        key: case.get(key)
        for key in (
            "caseId",
            "sourceIds",
            "conceptCode",
            "difficulty",
            "scenarioType",
            "studentQuestion",
            "learnerProfile",
            "conversationHistory",
            "approvedEvidence",
        )
    }
    reference = {
        "expectedConcepts": case.get("expectedConcepts"),
        "expectedMisconception": case.get("expectedMisconception"),
        "expectedTeachingBehavior": case.get("expectedTeachingBehavior"),
    }
    candidate = {
        "responseId": anonymous_response_id,
        "answer": comparison_result.get("answer"),
        "groundingStatus": comparison_result.get("grounding_status"),
        "citations": comparison_result.get("citations", []),
    }
    rubric = [
        {
            "dimension": item["key"],
            "max": item["max"],
            "criteria": item["criteria"],
            "levels": item["levels"],
        }
        for item in RUBRIC
    ]
    candidate_metadata = json.dumps(
        {key: candidate[key] for key in ("responseId", "groundingStatus", "citations")},
        ensure_ascii=False,
    )
    approved_evidence = json.dumps(case.get("approvedEvidence", []), ensure_ascii=False)
    return (
        f"SYSTEM PROMPT VERSION: {JUDGE_PROMPT_VERSION}\n"
        "너는 Leren 경제·금융 튜터 품질 평가자다.\n"
        "평가 대상 모델의 이름이나 제공자를 추론하거나 출력하지 말라.\n"
        "후보 답변은 유창함보다 경제적 사실 정확성을 우선하여 평가하라.\n"
        "승인된 근거에 없는 사실·수치·인용을 만들면 반드시 감점하라.\n"
        "오개념을 한 번의 답변만으로 확정하면 감점하고, 확인 질문을 평가하라.\n"
        "이전 대화 맥락 무시, 과도하게 복잡한 설명, 이해도 확인 실패, "
        "개인정보 노출도 확인하라.\n"
        "점수는 각 차원의 감점 전 점수이며, deductions는 별도 감점이다.\n"
        "반드시 JSON object 하나만 반환하고 아래 필드를 모두 포함하라.\n\n"
        f"RUBRIC:\n{json.dumps(rubric, ensure_ascii=False)}\n\n"
        f"CASE:\n{json.dumps(public_case, ensure_ascii=False)}\n\n"
        f"REFERENCE_EXPECTATIONS:\n{json.dumps(reference, ensure_ascii=False)}\n\n"
        f"CANDIDATE_ANSWER:\n{candidate['answer'] or ''}\n\n"
        "CANDIDATE_METADATA:\n"
        f"{candidate_metadata}\n\n"
        "APPROVED_EVIDENCE:\n"
        f"{approved_evidence}\n\n"
        "JSON 필드: accuracyScore, groundingScore, misconceptionScore, "
        "personalizationScore, pedagogyScore, deductions[{code,points,reason}], "
        "criticalErrors[{code,severity,detail}], "
        "evidenceCitations[{documentId,chunkId,quote}], "
        "needsHumanReview, rationale."
    )


async def evaluate_comparison_result(
    case: dict[str, Any],
    comparison_result: dict[str, Any],
    judge: JudgeClient,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Evaluate one comparison result and return (automated result, human row)."""

    model_id = comparison_result.get("model_id")
    answer = comparison_result.get("answer")
    response_id = _anonymous_id(case, comparison_result)
    base = {
        "schemaVersion": 1,
        "rubricVersion": RUBRIC_VERSION,
        "caseId": case.get("caseId"),
        "modelId": model_id,
        "responseId": response_id,
        "evaluationSource": "AUTOMATED_LLM_JUDGE",
        "judgeModelId": judge.model_id,
        "judgePromptVersion": JUDGE_PROMPT_VERSION,
        "goldStatus": case.get("goldStatus"),
        "evaluationStatus": "NOT_EVALUATED",
        "accuracyScore": None,
        "groundingScore": None,
        "misconceptionScore": None,
        "personalizationScore": None,
        "pedagogyScore": None,
        "totalEducationScore": None,
        "deductions": [],
        "criticalErrors": [],
        "needsHumanReview": True,
        "citationValidation": {"status": "NOT_RUN", "errors": []},
        "automaticChecks": {},
        "judgeUsage": None,
    }

    schema_errors = validate_tutor_case_schema(case)
    eligible, gate_reasons = gold_gate(case)
    base["automaticChecks"] = {
        "jsonSchema": {
            "status": "PASS" if not schema_errors else "FAIL",
            "errors": schema_errors,
        },
        "goldGate": {
            "status": "PASS" if eligible else "BLOCKED",
            "reasons": gate_reasons,
        },
    }
    human_row = _human_review_row(case, comparison_result, response_id, eligible)
    if schema_errors:
        base["evaluationStatus"] = "NOT_EVALUATED_INVALID_CASE"
        base["criticalErrors"] = [
            _critical("JUDGE_OUTPUT_INVALID", "평가 입력 구조가 유효하지 않음")
        ]
        return base, human_row
    if not eligible:
        base["evaluationStatus"] = "NOT_EVALUATED_UNREVIEWED_GOLD"
        base["criticalErrors"] = [_critical("UNREVIEWED_GOLD", "; ".join(gate_reasons))]
        return base, human_row
    if (
        comparison_result.get("status") not in SUCCESS_STATUSES
        or not str(answer or "").strip()
    ):
        base["evaluationStatus"] = "NOT_EVALUATED_MODEL_ERROR"
        base["criticalErrors"] = [
            _critical(
                "MODEL_EXECUTION_ERROR",
                "후보 모델 응답이 없어 품질 점수를 계산하지 않음",
            )
        ]
        return base, human_row

    prompt = build_judge_prompt(
        case,
        comparison_result,
        anonymous_response_id=response_id,
    )
    started = time.perf_counter()
    try:
        judge_response = await judge.complete(prompt)
        payload = parse_judge_payload(judge_response.text)
    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
        base["evaluationStatus"] = "NOT_EVALUATED_JUDGE_ERROR"
        base["criticalErrors"] = [_critical("JUDGE_OUTPUT_INVALID", str(exc))]
        base["automaticChecks"]["judge"] = {"status": "FAIL"}
        base["judgeLatencyMs"] = _elapsed_ms(started)
        return base, human_row
    except Exception as exc:
        base["evaluationStatus"] = "NOT_EVALUATED_JUDGE_ERROR"
        base["criticalErrors"] = [_critical("JUDGE_OUTPUT_INVALID", type(exc).__name__)]
        base["automaticChecks"]["judge"] = {"status": "FAIL"}
        base["judgeLatencyMs"] = _elapsed_ms(started)
        return base, human_row

    citation_check = validate_judge_citations(
        payload.evidence_citations, case.get("approvedEvidence", [])
    )
    automatic = automatic_checks(case, comparison_result, payload, citation_check)
    judge_errors = [
        _critical(item.code, item.detail, item.severity)
        for item in payload.critical_errors
    ]
    auto_errors = automatic["criticalErrors"]
    critical_errors = _unique_errors(judge_errors + auto_errors)
    deductions = [
        {
            "code": item.code,
            "points": round(item.points, 2),
            "reason": item.reason,
            "source": "judge",
        }
        for item in payload.deductions
    ]
    deductions.extend(_deductions_for_errors(critical_errors))
    score_values = {
        "accuracyScore": payload.accuracy_score,
        "groundingScore": payload.grounding_score,
        "misconceptionScore": payload.misconception_score,
        "personalizationScore": payload.personalization_score,
        "pedagogyScore": payload.pedagogy_score,
    }
    raw_total = sum(score_values.values())
    total = max(
        0.0,
        min(
            float(RUBRIC_MAX_SCORE),
            raw_total - sum(item["points"] for item in deductions),
        ),
    )
    base.update(
        score_values,
        totalEducationScore=round(total, 2),
        evaluationStatus="SCORED",
        deductions=deductions,
        criticalErrors=critical_errors,
        needsHumanReview=bool(payload.needs_human_review or critical_errors),
        citationValidation=citation_check,
        automaticChecks=automatic,
        judgeUsage=judge_response.usage,
        judgeLatencyMs=_elapsed_ms(started),
    )
    human_row["reviewStatus"] = (
        "PENDING_HUMAN_REVIEW" if base["needsHumanReview"] else "NOT_SELECTED"
    )
    return base, human_row


def parse_judge_payload(text: str) -> JudgePayload:
    """Parse strict JSON while accepting a fenced JSON response from a provider."""

    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", candidate).strip()
    if not candidate.startswith("{"):
        start = candidate.find("{")
        end = candidate.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Judge did not return a JSON object")
        candidate = candidate[start : end + 1]
    return JudgePayload.model_validate(json.loads(candidate))


def validate_judge_citations(
    citations: list[JudgeCitation], evidence: list[dict[str, Any]]
) -> dict[str, Any]:
    evidence_by_key = {
        (
            str(item.get("documentId", item.get("sourceId"))),
            str(item.get("chunkId")),
        ): item
        for item in evidence
    }
    errors: list[dict[str, str]] = []
    checked: list[dict[str, Any]] = []
    for raw_citation in citations:
        citation = (
            raw_citation
            if isinstance(raw_citation, JudgeCitation)
            else JudgeCitation.model_validate(raw_citation)
        )
        key = (citation.document_id, citation.chunk_id)
        source = evidence_by_key.get(key)
        if source is None:
            errors.append(
                {
                    "code": "JUDGE_CITATION_INVALID",
                    "detail": f"unknown citation {key[0]}/{key[1]}",
                }
            )
            continue
        quote_ok = _normalize(citation.quote) in _normalize(
            str(source.get("content", ""))
        )
        if not quote_ok:
            errors.append(
                {
                    "code": "JUDGE_QUOTE_NOT_IN_APPROVED_SOURCE",
                    "detail": f"quote mismatch for {key[0]}/{key[1]}",
                }
            )
        checked.append(
            {"documentId": key[0], "chunkId": key[1], "quoteValid": quote_ok}
        )
    return {
        "status": "PASS" if not errors else "FAIL",
        "checked": checked,
        "errors": errors,
    }


def automatic_checks(
    case: dict[str, Any],
    comparison_result: dict[str, Any],
    payload: JudgePayload,
    citation_check: dict[str, Any],
) -> dict[str, Any]:
    answer = str(comparison_result.get("answer") or "")
    errors: list[dict[str, str]] = []
    approved_documents = _approved_documents(case.get("approvedEvidence", []))
    financial_evaluation = FinancialHallucinationEvaluator().evaluate(
        answer=_CITATION_PATTERN.sub("", answer),
        sources=approved_documents,
        history=[
            str(item.get("content", "")) for item in case.get("conversationHistory", [])
        ],
    )
    financial_findings = [
        {
            "type": finding.finding_type.value,
            "severity": finding.severity,
            "detail": finding.detail,
        }
        for finding in financial_evaluation.findings
        if finding.automatic
    ]
    if any(
        finding["type"] == FinancialFindingType.UNSUPPORTED_NUMERIC_CLAIM.value
        for finding in financial_findings
    ):
        errors.append(
            _critical(
                "ECONOMIC_FACT_ERROR",
                "근거에 없는 경제·금융 수치가 답변에 포함됨",
                "critical",
            )
        )
    if citation_check["status"] != "PASS":
        errors.append(
            _critical(
                "UNSUPPORTED_EVIDENCE", "Judge 인용문이 승인 원문과 일치하지 않음"
            )
        )
    answer_refs = _CITATION_PATTERN.findall(answer)
    approved_keys = {
        (str(item.get("documentId", item.get("sourceId"))), str(item.get("chunkId")))
        for item in case.get("approvedEvidence", [])
    }
    unsupported_answer_refs = [
        f"{doc}/{chunk}"
        for doc, chunk in answer_refs
        if (doc, chunk) not in approved_keys
    ]
    if unsupported_answer_refs:
        errors.append(_critical("UNSUPPORTED_EVIDENCE", "답변 출처가 승인 근거에 없음"))
    if case.get("scenarioType") == "D_MULTITURN_CONTEXT" and _context_ignored(
        case, answer
    ):
        errors.append(
            _critical(
                "CONTEXT_IGNORED", "이전 멀티턴 맥락을 활용한 흔적이 부족함", "high"
            )
        )
    if case.get("scenarioType") in {
        "A_CONCEPT_EXPLANATION",
        "B_MISCONCEPTION_DIAGNOSIS",
        "C_PERSONALIZED_LEARNING",
        "D_MULTITURN_CONTEXT",
    } and not _has_understanding_check(answer):
        errors.append(
            _critical(
                "UNDERSTANDING_CHECK_MISSING",
                "이해도 확인 질문 또는 확인 행동이 없음",
                "medium",
            )
        )
    if len(answer) > 1800:
        errors.append(
            _critical(
                "OVERCOMPLEX_EXPLANATION", "답변이 평가 한도보다 지나치게 김", "medium"
            )
        )
    privacy = _privacy_findings(answer, case.get("learnerProfile", {}))
    if privacy:
        errors.append(
            _critical("PERSONAL_DATA_EXPOSURE", ", ".join(privacy), "critical")
        )
    return {
        "citation": citation_check,
        "groundingValidator": _grounding_validator_result(answer, approved_documents),
        "financial": {
            "status": "FAIL" if financial_findings else "PASS",
            "findings": financial_findings,
        },
        "answerReferences": {
            "count": len(answer_refs),
            "unsupported": unsupported_answer_refs,
        },
        "privacy": {"status": "FAIL" if privacy else "PASS", "findings": privacy},
        "criticalErrors": errors,
        "judgeCriticalErrors": [item.code for item in payload.critical_errors],
    }


def _approved_documents(evidence: list[dict[str, Any]]) -> list[RetrievedDocument]:
    return [
        RetrievedDocument(
            content=str(item.get("content", "")),
            source=str(item.get("source", "approved-evidence")),
            document_id=str(item.get("documentId", item.get("sourceId", ""))),
            chunk_id=str(item.get("chunkId", "")),
            review_status=str(item.get("approvalStatus", "unknown")),
            license=str(item.get("licenseStatus", "unknown")),
        )
        for item in evidence
        if str(item.get("content", "")).strip()
    ]


def _grounding_validator_result(
    answer: str, documents: list[RetrievedDocument]
) -> dict[str, Any]:
    if not documents:
        return {"status": "NOT_RUN", "valid": False, "grounded": False}
    result = CitationValidator().validate_and_build(answer, documents)
    return {
        "status": "PASS" if result.valid else "FAIL",
        "valid": result.valid,
        "grounded": result.grounded,
        "unsupportedReferences": result.unsupported_references,
    }


def deduction_report(records: list[dict[str, Any]]) -> str:
    """Render a compact analysis report without exposing evaluator prompts."""

    evaluated = [item for item in records if item.get("evaluationStatus") == "SCORED"]
    status_counts = _counts(item.get("evaluationStatus") for item in records)
    error_counts = _counts(
        error.get("code")
        for item in records
        for error in item.get("criticalErrors", [])
    )
    deduction_counts = _counts(
        deduction.get("code")
        for item in records
        for deduction in item.get("deductions", [])
    )
    average = (
        round(
            sum(float(item["totalEducationScore"]) for item in evaluated)
            / len(evaluated),
            2,
        )
        if evaluated
        else None
    )
    lines = [
        "# Tutor 교육 품질 60점 평가 감점 분석",
        "",
        f"- Rubric: `{RUBRIC_VERSION}`",
        f"- 평가 결과 건수: {len(records)}",
        f"- 실제 점수 부여 건수: {len(evaluated)}",
        f"- 평균 총점: {average if average is not None else 'N/A'} "
        f"/ {RUBRIC_MAX_SCORE}",
        f"- 상태별: `{json.dumps(status_counts, ensure_ascii=False)}`",
        "- 사람 검토 필요: "
        f"{sum(bool(item.get('needsHumanReview')) for item in records)}건",
        "",
        "## 중대 오류 코드",
        "",
        f"`{json.dumps(error_counts, ensure_ascii=False)}`",
        "",
        "## 감점 코드",
        "",
        f"`{json.dumps(deduction_counts, ensure_ascii=False)}`",
        "",
        "## 안전 정책",
        "",
        "- `INDEPENDENT_APPROVED`가 아닌 사례에는 최종 점수를 부여하지 않는다.",
        "- Judge가 반환한 인용문은 승인 원문에 포함되는지 자동 검증한다.",
        "- 자동 Judge 결과와 익명 사람 검토 결과는 별도 파일·필드로 관리한다.",
    ]
    return "\n".join(lines) + "\n"


def write_jsonl(path: str | Path, rows: list[dict[str, Any]]) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        "".join(
            json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
        ),
        encoding="utf-8",
    )


def _human_review_row(
    case: dict[str, Any],
    comparison_result: dict[str, Any],
    response_id: str,
    eligible: bool,
) -> dict[str, Any]:
    public = {
        key: case.get(key)
        for key in (
            "studentQuestion",
            "learnerProfile",
            "conversationHistory",
            "approvedEvidence",
        )
    }
    return {
        "reviewSchemaVersion": "tutor-human-review-v1",
        "reviewId": response_id,
        "caseIdHash": hashlib.sha256(str(case.get("caseId")).encode()).hexdigest()[:16],
        "responseId": response_id,
        "evaluationSource": "HUMAN_REVIEW_PENDING",
        "reviewStatus": "PENDING_HUMAN_REVIEW"
        if eligible
        else "BLOCKED_UNREVIEWED_GOLD",
        "case": public,
        "candidateAnswer": _redact_pii(str(comparison_result.get("answer") or "")),
        "humanAccuracyScore": None,
        "humanGroundingScore": None,
        "humanMisconceptionScore": None,
        "humanPersonalizationScore": None,
        "humanPedagogyScore": None,
        "humanTotalEducationScore": None,
        "humanDeductions": None,
        "humanCriticalErrors": None,
        "reviewerId": None,
        "reviewedAt": None,
        "reviewNotes": None,
    }


def _anonymous_id(case: dict[str, Any], result: dict[str, Any]) -> str:
    raw = "|".join(
        str(result.get(key, "")) for key in ("model_id", "input_hash", "answer")
    )
    return hashlib.sha256(f"{case.get('caseId')}|{raw}".encode()).hexdigest()[:20]


def _critical(code: str, detail: str, severity: str = "high") -> dict[str, str]:
    return {"code": code, "severity": severity, "detail": detail}


def _deductions_for_errors(errors: list[dict[str, str]]) -> list[dict[str, Any]]:
    result = []
    seen: set[str] = set()
    for error in errors:
        code = error["code"]
        points = CRITICAL_ERROR_DEDUCTIONS.get(code, 0)
        if not points or code in seen:
            continue
        result.append(
            {
                "code": code,
                "points": points,
                "reason": error["detail"],
                "source": "automatic",
            }
        )
        seen.add(code)
    return result


def _unique_errors(errors: list[dict[str, str]]) -> list[dict[str, str]]:
    result = []
    seen: set[tuple[str, str]] = set()
    for error in errors:
        key = (error["code"], error["detail"])
        if key not in seen:
            result.append(error)
            seen.add(key)
    return result


def _context_ignored(case: dict[str, Any], answer: str) -> bool:
    history = case.get("conversationHistory", [])
    if not history:
        return False
    previous = " ".join(
        str(item.get("content", "")) for item in history if item.get("role") == "USER"
    )
    tokens = [
        token for token in re.findall(r"[가-힣A-Za-z]{2,}", previous) if len(token) >= 2
    ]
    if not tokens:
        return False
    answer_normalized = _normalize(answer)
    return not any(
        _normalize(token) in answer_normalized for token in tokens[:8]
    ) and not any(
        marker in answer for marker in ("앞선", "이전", "대화", "맥락", "그 질문")
    )


def _has_understanding_check(answer: str) -> bool:
    return "?" in answer or any(
        marker in answer for marker in ("이해", "확인해 보", "어떤", "말해 보")
    )


def _privacy_findings(answer: str, profile: Any) -> list[str]:
    findings = []
    if _EMAIL_PATTERN.search(answer) or _PHONE_PATTERN.search(answer):
        findings.append("answer contains an email or phone-like value")
    if isinstance(profile, dict):
        for key, value in profile.items():
            if (
                any(
                    token in str(key).casefold()
                    for token in ("email", "phone", "name", "address")
                )
                and value
                and str(value) in answer
            ):
                findings.append(f"answer repeats learnerProfile.{key}")
    return findings


def _redact_pii(value: str) -> str:
    value = _EMAIL_PATTERN.sub("<REDACTED_EMAIL>", value)
    return _PHONE_PATTERN.sub("<REDACTED_PHONE>", value)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _extract_block(prompt: str, name: str) -> str:
    marker = f"{name}:\n"
    start = prompt.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = prompt.find("\n\n", start)
    return prompt[start:] if end < 0 else prompt[start:end]


def _parse_json_block(value: str) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return None


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.perf_counter() - started) * 1000))


def _counts(values) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))
