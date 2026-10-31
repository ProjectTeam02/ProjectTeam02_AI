"""Prepare a grounded question-generation draft without calling an LLM.

Node.js remains responsible for persistence, grading, rewards, HP and stage
completion.  This module only validates the inputs that an approved future
question generator may receive.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True, slots=True)
class QuestionGenerationPlan:
    status: str
    concept_code: str
    stage_id: str
    blueprint: tuple[dict[str, Any], ...]
    evidence_document_ids: tuple[str, ...]
    prompt: str | None = None
    reason: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "concept_code": self.concept_code,
            "stage_id": self.stage_id,
            "blueprint": list(self.blueprint),
            "evidence_document_ids": list(self.evidence_document_ids),
            "prompt": self.prompt,
            "reason": self.reason,
        }


def prepare_question_generation(
    *,
    concept_code: str,
    stage_id: str,
    learning_goal: str,
    blueprint: Iterable[dict[str, Any]],
    evidence: Iterable[dict[str, Any]],
) -> QuestionGenerationPlan:
    """Build a prompt only from approved evidence and an existing blueprint."""
    blueprint_rows = tuple(row for row in blueprint if isinstance(row, dict))
    if not blueprint_rows:
        return QuestionGenerationPlan(
            status="BLOCKED_NEEDS_AUTHORING",
            concept_code=concept_code,
            stage_id=stage_id,
            blueprint=(),
            evidence_document_ids=(),
            reason="question_blueprint is empty or marked NEEDS_AUTHORING",
        )
    approved = tuple(
        row
        for row in evidence
        if isinstance(row, dict)
        and str(row.get("review_status", "")).casefold() == "approved"
        and str(row.get("document_id") or "").strip()
        and str(row.get("content") or row.get("content_preview") or "").strip()
    )
    if not approved:
        return QuestionGenerationPlan(
            status="BLOCKED_NO_APPROVED_EVIDENCE",
            concept_code=concept_code,
            stage_id=stage_id,
            blueprint=blueprint_rows,
            evidence_document_ids=(),
            reason="approved concept-document mapping is required before generation",
        )
    evidence_ids = tuple(dict.fromkeys(str(row["document_id"]) for row in approved))
    excerpts = []
    for row in approved:
        content = str(row.get("content") or row.get("content_preview") or "")
        excerpts.append(f"[{row['document_id']}] {content[:1200]}")
    prompt = (
        "Generate a draft only; do not invent facts outside the evidence.\n"
        f"Concept: {concept_code}\nStage: {stage_id}\nLearning goal: {learning_goal}\n"
        f"Blueprint: {list(blueprint_rows)}\nEvidence:\n" + "\n".join(excerpts)
    )
    return QuestionGenerationPlan(
        status="DRAFT_READY",
        concept_code=concept_code,
        stage_id=stage_id,
        blueprint=blueprint_rows,
        evidence_document_ids=evidence_ids,
        prompt=prompt,
    )
