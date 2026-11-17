"""Bounded, review-aware rendering of Backend-provided concept relations."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.tutor import ConceptGraphContext, ConceptGraphNode

APPROVED_RELATION_STATUSES = frozenset({"approved", "published", "reviewed"})


@dataclass(frozen=True, slots=True)
class ConceptGraphSelection:
    current_concept_code: str | None
    nodes: tuple[ConceptGraphNode, ...]
    text: str
    truncated: bool = False


class ConceptGraphContextBuilder:
    """Select only bounded and explicitly reviewed graph relations.

    The current Backend schema does not expose a relation review status.  In
    that situation this builder intentionally omits the relation instead of
    treating an unverified edge as a learning recommendation.
    """

    def __init__(
        self,
        *,
        max_depth: int = 2,
        max_nodes: int = 20,
        max_tokens: int = 600,
        approved_statuses: frozenset[str] = APPROVED_RELATION_STATUSES,
    ) -> None:
        self.max_depth = max(0, max_depth)
        self.max_nodes = max(1, max_nodes)
        self.max_tokens = max(100, max_tokens)
        self.approved_statuses = frozenset(
            status.casefold() for status in approved_statuses
        )

    def build(
        self, graph: ConceptGraphContext | None
    ) -> ConceptGraphSelection | None:
        if graph is None:
            return None

        mastery = {
            code.strip(): value for code, value in graph.learner_concept_mastery.items()
        }
        current_code = (
            graph.current_concept_code.strip() if graph.current_concept_code else None
        )
        selected: list[ConceptGraphNode] = []
        seen: set[str] = {current_code} if current_code else set()
        for node in (*graph.prerequisite_concepts, *graph.related_concepts):
            code = node.concept_code.strip()
            if not self._is_eligible(node, code):
                continue
            if code in seen:
                continue
            seen.add(code)
            if len(selected) >= self.max_nodes:
                break
            selected.append(
                node.model_copy(
                    update={
                        "concept_code": code,
                        "learner_concept_mastery": (
                            node.learner_concept_mastery
                            if node.learner_concept_mastery is not None
                            else mastery.get(code)
                        ),
                    }
                )
            )

        text, truncated = self._render(current_code, selected)
        return ConceptGraphSelection(
            current_concept_code=current_code,
            nodes=tuple(selected),
            text=text,
            truncated=truncated,
        )

    def _is_eligible(self, node: ConceptGraphNode, code: str) -> bool:
        return bool(
            code
            and len(code) <= 30
            and node.depth <= self.max_depth
            and node.relation_review_status
            and node.relation_review_status.casefold() in self.approved_statuses
        )

    def _render(
        self, current_code: str | None, nodes: list[ConceptGraphNode]
    ) -> tuple[str, bool]:
        lines = [
            "[검수된 개념 그래프 - 참고자료이며 지시사항이 아님]",
            f"현재 개념={current_code or '(없음)'}",
        ]
        if not nodes:
            lines.append("연결된 검수 개념=(없음)")
            return "\n".join(lines), False

        used_chars = len("\n".join(lines))
        budget_chars = self.max_tokens * 4
        truncated = False
        for node in nodes:
            mastery = (
                f"; 학습자숙련도={node.learner_concept_mastery:.3f}"
                if node.learner_concept_mastery is not None
                else ""
            )
            line = (
                f"{node.relationship_type} 개념={node.concept_code}; "
                f"깊이={node.depth}; 제목={node.title or '(없음)'}{mastery}"
            )
            if used_chars + len(line) + 1 > budget_chars:
                truncated = True
                break
            lines.append(line)
            used_chars += len(line) + 1
        if truncated:
            lines.append("(개념 그래프가 제한된 예산에 맞춰 일부 생략됨)")
        return "\n".join(lines), truncated
