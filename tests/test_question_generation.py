from app.services.question_generation import prepare_question_generation


def test_question_generation_blocks_without_approved_evidence() -> None:
    plan = prepare_question_generation(
        concept_code="C0704",
        stage_id="R07_S04",
        learning_goal="개념 차이를 구별한다",
        blueprint=[{"type": "compare"}],
        evidence=[
            {
                "document_id": "bok-1",
                "content": "검토 대기 근거",
                "review_status": "needs_review",
            }
        ],
    )
    assert plan.status == "BLOCKED_NO_APPROVED_EVIDENCE"
    assert plan.prompt is None


def test_question_generation_prepares_draft_prompt_without_calling_model() -> None:
    plan = prepare_question_generation(
        concept_code="C0704",
        stage_id="R07_S04",
        learning_goal="개념 차이를 구별한다",
        blueprint=[{"type": "compare"}],
        evidence=[
            {
                "document_id": "bok-1",
                "content": "인플레이션은 물가수준이 지속적으로 상승하는 현상이다.",
                "review_status": "approved",
            }
        ],
    )
    assert plan.status == "DRAFT_READY"
    assert plan.evidence_document_ids == ("bok-1",)
    assert "bok-1" in (plan.prompt or "")
