from __future__ import annotations

import json

import pytest

from app.evaluation.tutor_quality import (
    JudgeResponse,
    MockJudgeClient,
    build_judge_prompt,
    evaluate_comparison_result,
    parse_judge_payload,
    validate_judge_citations,
    validate_tutor_case_schema,
)


def reviewed_case(
    *,
    scenario_type: str = "A_CONCEPT_EXPLANATION",
    gold_status: str = "INDEPENDENT_APPROVED",
) -> dict:
    return {
        "caseId": "TUTOR-001",
        "sourceIds": ["DOC-1"],
        "conceptCode": "ECON-001",
        "difficulty": "easy",
        "scenarioType": scenario_type,
        "studentQuestion": "기준금리는 무엇인가요?",
        "learnerProfile": {"estimatedMastery": 0.4, "learningPreference": "plain"},
        "conversationHistory": [],
        "approvedEvidence": [
            {
                "sourceId": "DOC-1",
                "documentId": "DOC-1",
                "chunkId": "DOC-1:chunk-1",
                "content": "기준금리는 중앙은행이 정하는 정책금리입니다.",
                "approvalStatus": "approved",
                "licenseStatus": "approved",
            }
        ],
        "expectedConcepts": ["기준금리"],
        "expectedMisconception": None,
        "expectedTeachingBehavior": ["cite_source", "check_understanding"],
        "goldStatus": gold_status,
    }


def comparison_result(answer: str, *, model_id: str = "secret/model-a") -> dict:
    return {
        "case_id": "TUTOR-001",
        "model_id": model_id,
        "status": "mock",
        "input_hash": "input-hash",
        "answer": answer,
        "grounding_status": "GROUNDED",
        "citations": [{"document_id": "DOC-1", "chunk_id": "DOC-1:chunk-1"}],
    }


@pytest.mark.asyncio
async def test_normal_response_is_scored_with_60_point_components() -> None:
    result, human = await evaluate_comparison_result(
        reviewed_case(),
        comparison_result(
            "기준금리는 중앙은행이 정하는 정책금리입니다. 이해했나요? "
            "[출처: DOC-1/DOC-1:chunk-1]"
        ),
        MockJudgeClient(),
    )

    assert result["evaluationStatus"] == "SCORED"
    assert result["totalEducationScore"] == 57.0
    assert result["accuracyScore"] == 14.0
    assert result["groundingScore"] == 10.0
    assert result["needsHumanReview"] is False
    assert human["reviewStatus"] == "NOT_SELECTED"
    assert "modelId" not in human


@pytest.mark.asyncio
async def test_economic_error_and_causal_error_are_deducted() -> None:
    result, _ = await evaluate_comparison_result(
        reviewed_case(),
        comparison_result(
            "[WRONG] 기준금리가 오르면 물가는 항상 즉시 내려갑니다. "
            "[출처: DOC-1/DOC-1:chunk-1]"
        ),
        MockJudgeClient(),
    )

    assert result["evaluationStatus"] == "SCORED"
    codes = {item["code"] for item in result["criticalErrors"]}
    deduction_codes = {item["code"] for item in result["deductions"]}
    assert {"ECONOMIC_FACT_ERROR", "CAUSAL_ERROR"} <= codes
    assert {"ECONOMIC_FACT_ERROR", "CAUSAL_ERROR"} <= deduction_codes
    assert result["totalEducationScore"] < 57
    assert result["needsHumanReview"] is True


@pytest.mark.asyncio
async def test_invalid_judge_json_is_not_scored() -> None:
    class InvalidJudge:
        model_id = "mock/invalid"

        async def complete(self, prompt: str) -> JudgeResponse:
            del prompt
            return JudgeResponse(text="not json")

    result, _ = await evaluate_comparison_result(
        reviewed_case(),
        comparison_result("기준금리 설명입니다? [출처: DOC-1/DOC-1:chunk-1]"),
        InvalidJudge(),
    )

    assert result["evaluationStatus"] == "NOT_EVALUATED_JUDGE_ERROR"
    assert result["totalEducationScore"] is None
    assert result["criticalErrors"][0]["code"] == "JUDGE_OUTPUT_INVALID"


@pytest.mark.asyncio
async def test_judge_quote_must_exist_in_approved_source() -> None:
    class MismatchJudge:
        model_id = "mock/mismatch"

        async def complete(self, prompt: str) -> JudgeResponse:
            del prompt
            payload = {
                "accuracyScore": 10,
                "groundingScore": 10,
                "misconceptionScore": 10,
                "personalizationScore": 10,
                "pedagogyScore": 10,
                "deductions": [],
                "criticalErrors": [],
                "evidenceCitations": [
                    {
                        "documentId": "DOC-1",
                        "chunkId": "DOC-1:chunk-1",
                        "quote": "승인 원문에 없는 문장",
                    }
                ],
                "needsHumanReview": False,
                "rationale": {},
            }
            return JudgeResponse(text=json.dumps(payload, ensure_ascii=False))

    result, _ = await evaluate_comparison_result(
        reviewed_case(),
        comparison_result("설명입니다? [출처: DOC-1/DOC-1:chunk-1]"),
        MismatchJudge(),
    )

    assert result["citationValidation"]["status"] == "FAIL"
    assert any(
        item["code"] == "UNSUPPORTED_EVIDENCE" for item in result["criticalErrors"]
    )
    assert result["needsHumanReview"] is True


@pytest.mark.asyncio
async def test_misconception_misdiagnosis_is_recorded_as_critical() -> None:
    class DiagnosisJudge:
        model_id = "mock/diagnosis"

        async def complete(self, prompt: str) -> JudgeResponse:
            del prompt
            payload = {
                "accuracyScore": 12,
                "groundingScore": 10,
                "misconceptionScore": 2,
                "personalizationScore": 8,
                "pedagogyScore": 8,
                "deductions": [],
                "criticalErrors": [
                    {
                        "code": "MISCONCEPTION_MISDIAGNOSIS",
                        "severity": "critical",
                        "detail": "한 번의 답변으로 오개념을 확정함",
                    }
                ],
                "evidenceCitations": [],
                "needsHumanReview": True,
                "rationale": {},
            }
            return JudgeResponse(text=json.dumps(payload, ensure_ascii=False))

    case = reviewed_case(scenario_type="B_MISCONCEPTION_DIAGNOSIS")
    result, _ = await evaluate_comparison_result(
        case,
        comparison_result("당신은 확실히 틀렸습니다?"),
        DiagnosisJudge(),
    )

    assert result["evaluationStatus"] == "SCORED"
    assert result["totalEducationScore"] == 30.0
    assert result["deductions"][0]["code"] == "MISCONCEPTION_MISDIAGNOSIS"


@pytest.mark.asyncio
async def test_unreviewed_gold_never_receives_a_final_score() -> None:
    result, human = await evaluate_comparison_result(
        reviewed_case(gold_status="PENDING_REVIEW"),
        comparison_result("기준금리 설명입니다."),
        MockJudgeClient(),
    )

    assert result["evaluationStatus"] == "NOT_EVALUATED_UNREVIEWED_GOLD"
    assert result["totalEducationScore"] is None
    assert result["needsHumanReview"] is True
    assert human["reviewStatus"] == "BLOCKED_UNREVIEWED_GOLD"


def test_prompt_hides_target_model_name_and_schema_rejects_bad_case() -> None:
    case = reviewed_case()
    prompt = build_judge_prompt(
        case,
        comparison_result("응답입니다.", model_id="provider/secret-model"),
        anonymous_response_id="anon-1",
    )

    assert "provider/secret-model" not in prompt
    assert "anon-1" in prompt
    assert validate_tutor_case_schema({"caseId": "broken"})


def test_citation_validator_rejects_unknown_and_accepts_exact_quote() -> None:
    evidence = [
        {
            "documentId": "DOC-1",
            "chunkId": "CHUNK-1",
            "content": "승인된 원문입니다.",
        }
    ]

    valid = validate_judge_citations(
        [
            {
                "documentId": "DOC-1",
                "chunkId": "CHUNK-1",
                "quote": "승인된 원문입니다.",
            }
        ],
        evidence,
    )
    invalid = validate_judge_citations(
        [
            {
                "documentId": "DOC-2",
                "chunkId": "CHUNK-2",
                "quote": "없는 원문",
            }
        ],
        evidence,
    )

    assert valid["status"] == "PASS"
    assert invalid["status"] == "FAIL"


def test_parse_judge_payload_accepts_json_fence() -> None:
    payload = {
        "accuracyScore": 1,
        "groundingScore": 1,
        "misconceptionScore": 1,
        "personalizationScore": 1,
        "pedagogyScore": 1,
        "deductions": [],
        "criticalErrors": [],
        "evidenceCitations": [],
        "needsHumanReview": False,
    }

    parsed = parse_judge_payload(f"```json\n{json.dumps(payload)}\n```")

    assert parsed.accuracy_score == 1
