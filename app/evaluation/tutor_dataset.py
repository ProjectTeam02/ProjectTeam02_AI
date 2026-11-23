"""Build and validate the human-review-first tutor evaluation dataset."""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable, Sequence

from app.dataset_pipeline.io import NormalizedDocument

SEED = 20261122
TARGET_COUNT = 100
DIFFICULTY_COUNTS = {"easy": 34, "medium": 33, "hard": 33}
SCENARIO_TYPE_COUNTS = {
    "A_CONCEPT_EXPLANATION": 20,
    "B_MISCONCEPTION_DIAGNOSIS": 25,
    "C_PERSONALIZED_LEARNING": 25,
    "D_MULTITURN_CONTEXT": 20,
    "E_INSUFFICIENT_EVIDENCE": 10,
}
MISCONCEPTION_TYPES = (
    "KNOWLEDGE_GAP",
    "RELATION_ERROR",
    "CAUSAL_ERROR",
    "APPLICATION_ERROR",
    "UNCERTAIN",
)
REQUIRED_FIELDS = {
    "caseId",
    "sourceIds",
    "conceptCode",
    "difficulty",
    "scenarioType",
    "studentQuestion",
    "learnerProfile",
    "conversationHistory",
    "approvedEvidence",
    "expectedConcepts",
    "expectedMisconception",
    "expectedTeachingBehavior",
    "goldStatus",
}
PUBLIC_MODEL_FIELDS = {
    "caseId",
    "sourceIds",
    "conceptCode",
    "difficulty",
    "scenarioType",
    "studentQuestion",
    "learnerProfile",
    "conversationHistory",
    "approvedEvidence",
}
SENSITIVE_KEY_PARTS = (
    "email",
    "phone",
    "mobile",
    "address",
    "full_name",
    "real_name",
    "person_name",
    "student_name",
    "user_id",
    "userid",
    "learner_id",
    "learnerid",
    "ssn",
)
EMAIL_PATTERN = re.compile(r"\b[^\s@]+@[^\s@]+\.[^\s@]+\b")
PHONE_PATTERN = re.compile(r"(?<!\d)(?:\+?\d[\d\s-]{7,}\d)(?!\d)")


def build_tutor_dataset(
    documents: Sequence[NormalizedDocument],
    *,
    seed: int = SEED,
    evidence_chunks: dict[str, list[dict[str, Any]]] | None = None,
) -> list[dict[str, Any]]:
    """Create deterministic scenarios from canonical source documents only."""

    import random

    by_source: dict[str, list[NormalizedDocument]] = {"KDI": [], "BOK": []}
    for document in documents:
        if document.source in by_source and document.content.strip():
            by_source[document.source].append(document)
    rng = random.Random(seed)
    selected: list[NormalizedDocument] = []
    for source in ("KDI", "BOK"):
        unique = _unique_content_documents(sorted(by_source[source], key=_doc_key))
        if len(unique) < TARGET_COUNT // 2:
            raise ValueError(f"{source} has fewer than 50 unique source documents")
        selected.extend(rng.sample(unique, TARGET_COUNT // 2))

    scenario_types = _shuffled_slots(SCENARIO_TYPE_COUNTS, rng)
    difficulties = _shuffled_slots(DIFFICULTY_COUNTS, rng)
    rows: list[dict[str, Any]] = []
    misconception_index = 0
    for index, (document, scenario_type, difficulty) in enumerate(
        zip(selected, scenario_types, difficulties), start=1
    ):
        misconception_type = MISCONCEPTION_TYPES[
            misconception_index % len(MISCONCEPTION_TYPES)
        ]
        if scenario_type == "B_MISCONCEPTION_DIAGNOSIS":
            misconception_index += 1
        rows.append(
            _scenario_row(
                index=index,
                document=document,
                scenario_type=scenario_type,
                difficulty=difficulty,
                misconception_type=misconception_type,
                evidence_chunks=evidence_chunks or {},
            )
        )
    return rows


def validate_tutor_dataset(
    rows: Sequence[dict[str, Any]],
    documents: Sequence[NormalizedDocument],
) -> dict[str, Any]:
    """Return structural, lineage, privacy, and review-readiness validation."""

    document_by_id = {document.document_id: document for document in documents}
    errors: list[str] = []
    warnings: list[str] = []
    duplicate_case_ids = _duplicates(str(row.get("caseId")) for row in rows)
    if len(rows) != TARGET_COUNT:
        errors.append(f"expected {TARGET_COUNT} rows, found {len(rows)}")
    if duplicate_case_ids:
        errors.append(f"duplicate caseId values: {sorted(duplicate_case_ids)}")

    for row_index, row in enumerate(rows, start=1):
        missing = sorted(REQUIRED_FIELDS - set(row))
        if missing:
            errors.append(f"row {row_index} missing fields: {', '.join(missing)}")
        source_ids = row.get("sourceIds", [])
        if not isinstance(source_ids, list) or not source_ids:
            errors.append(f"row {row_index} sourceIds must be a non-empty list")
        for source_id in source_ids if isinstance(source_ids, list) else []:
            if source_id not in document_by_id:
                errors.append(f"row {row_index} has unknown sourceId {source_id}")
        if row.get("difficulty") not in DIFFICULTY_COUNTS:
            errors.append(f"row {row_index} has invalid difficulty")
        if row.get("scenarioType") not in SCENARIO_TYPE_COUNTS:
            errors.append(f"row {row_index} has invalid scenarioType")
        if row.get("goldStatus") != "PENDING_REVIEW":
            errors.append(f"row {row_index} is not PENDING_REVIEW")
        if row.get("conceptCode") is not None:
            warnings.append(
                f"row {row_index} has a conceptCode requiring provenance review"
            )
        _validate_history(row, row_index, errors)
        _validate_evidence(row, row_index, document_by_id, errors)
        privacy_findings = _privacy_findings(row)
        errors.extend(
            f"row {row_index} privacy finding: {finding}"
            for finding in privacy_findings
        )
        if set(public_model_input(row)) & {
            "expectedConcepts",
            "expectedMisconception",
            "expectedTeachingBehavior",
            "goldStatus",
        }:
            errors.append(
                f"row {row_index} exposes evaluator-only fields to model input"
            )

    difficulty_counts = Counter(str(row.get("difficulty")) for row in rows)
    scenario_counts = Counter(str(row.get("scenarioType")) for row in rows)
    source_counts = Counter(
        document_by_id[source_id].source
        for row in rows
        for source_id in row.get("sourceIds", [])
        if source_id in document_by_id
    )
    gold_counts = Counter(str(row.get("goldStatus")) for row in rows)
    approval_counts = Counter(
        str(evidence.get("approvalStatus"))
        for row in rows
        for evidence in row.get("evidenceCandidates", [])
    )
    approved_evidence_count = sum(len(row.get("approvedEvidence", [])) for row in rows)
    independent_gold_ready = bool(rows) and all(
        row.get("goldStatus") == "INDEPENDENT_APPROVED" for row in rows
    )
    if approved_evidence_count == 0:
        warnings.append("no evidence has an explicit approved status")
    if not independent_gold_ready:
        warnings.append("independent Gold review is not complete")
    if any(
        document.source_review_status.casefold() != "approved" for document in documents
    ):
        warnings.append(
            "canonical source review status is unresolved for at least one "
            "source document"
        )
    if any(
        document.license_status.casefold() not in {"approved", "cleared", "verified"}
        for document in documents
    ):
        warnings.append(
            "canonical license status is unresolved for at least one source document"
        )

    return {
        "valid": not errors,
        "ready_for_scoring": (
            not errors and independent_gold_ready and approved_evidence_count > 0
        ),
        "errors": errors,
        "warnings": warnings,
        "row_count": len(rows),
        "duplicate_case_ids": sorted(duplicate_case_ids),
        "difficulty_counts": dict(sorted(difficulty_counts.items())),
        "scenario_type_counts": dict(sorted(scenario_counts.items())),
        "source_counts": dict(sorted(source_counts.items())),
        "gold_status_counts": dict(sorted(gold_counts.items())),
        "candidate_evidence_approval_status_counts": dict(
            sorted(approval_counts.items())
        ),
        "approved_evidence_count": approved_evidence_count,
        "concept_code_missing_count": sum(
            row.get("conceptCode") is None for row in rows
        ),
        "independent_gold_ready": independent_gold_ready,
        "privacy_findings": sum(len(_privacy_findings(row)) for row in rows),
    }


def public_model_input(row: dict[str, Any]) -> dict[str, Any]:
    """Project a scenario without expected answers, behavior, or Gold fields."""

    return {key: row[key] for key in PUBLIC_MODEL_FIELDS if key in row}


def dataset_manifest(
    rows: Sequence[dict[str, Any]],
    corpus_inventory: dict[str, Any],
    validation: dict[str, Any],
    *,
    seed: int = SEED,
) -> dict[str, Any]:
    return {
        "dataset_name": "Leren tutor evaluation scenarios",
        "schema_version": "tutor-test-100-v1",
        "seed": seed,
        "target_count": TARGET_COUNT,
        "actual_count": len(rows),
        "source_dataset": {
            "canonical_rule": corpus_inventory.get("canonical_counting_rule"),
            "dataset_version": corpus_inventory.get("dataset_version"),
            "document_count": corpus_inventory.get("document_count"),
            "document_count_by_source": corpus_inventory.get(
                "document_count_by_source"
            ),
            "source_data_modified": False,
        },
        "scenario_distribution": {
            "difficulty": validation["difficulty_counts"],
            "scenario_type": validation["scenario_type_counts"],
            "source": validation["source_counts"],
        },
        "review": {
            "gold_status": validation["gold_status_counts"],
            "approved_evidence_count": validation["approved_evidence_count"],
            "independent_gold_ready": validation["independent_gold_ready"],
        },
        "missing_inputs": [
            "canonical conceptCode mapping/curriculum is not present "
            "in the local corpus",
            "source review and license approval are unresolved in "
            "the canonical exports",
            "independent human Gold review is not complete",
        ],
        "model_input_policy": (
            "Only public_model_input(row) may be passed to a model. Expected concepts, "
            "misconception hypotheses, teaching behavior, and Gold status "
            "are evaluator-only."
        ),
    }


def _scenario_row(
    *,
    index: int,
    document: NormalizedDocument,
    scenario_type: str,
    difficulty: str,
    misconception_type: str,
    evidence_chunks: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    term = _term(document.title)
    related = list(document.related_terms)
    expected_concepts = [term] + [item for item in related if item and item != term]
    candidate_evidence = _candidate_evidence(
        document, evidence_chunks.get(document.document_id, [])
    )
    approved_evidence = [
        item
        for item in candidate_evidence
        if item["approvalStatus"] == "approved"
        and item["licenseStatus"] in {"approved", "cleared", "verified"}
    ]
    row: dict[str, Any] = {
        "caseId": f"TUTOR-{index:03d}",
        "sourceIds": [document.document_id],
        "conceptCode": None,
        "conceptCodeStatus": "MISSING_CANONICAL_CURRICULUM",
        "difficulty": difficulty,
        "scenarioType": scenario_type,
        "studentQuestion": _question(term, scenario_type, difficulty),
        "learnerProfile": _profile(index, term, scenario_type),
        "conversationHistory": _history(term, scenario_type, difficulty),
        "approvedEvidence": approved_evidence,
        "evidenceCandidates": candidate_evidence,
        "expectedConcepts": expected_concepts,
        "expectedMisconception": (
            _misconception(term, misconception_type)
            if scenario_type == "B_MISCONCEPTION_DIAGNOSIS"
            else None
        ),
        "expectedTeachingBehavior": _teaching_behavior(scenario_type),
        "goldStatus": "PENDING_REVIEW",
        "goldReview": {
            "reviewerId": None,
            "reviewedAt": None,
            "reviewMode": None,
        },
        "generation": {
            "method": "deterministic_template_from_canonical_source",
            "sourceReviewStatus": document.source_review_status,
            "licenseStatus": document.license_status,
            "sourceContentHash": document.text_hash,
        },
    }
    return row


def _candidate_evidence(
    document: NormalizedDocument,
    chunks: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected = sorted(chunks, key=lambda item: str(item.get("chunk_id", "")))[:2]
    if not selected:
        selected = [
            {
                "chunk_id": f"{document.source}:{document.document_id}:chunk-0000",
                "content": document.content,
                "text_hash": document.text_hash,
            }
        ]
    return [
        {
            "sourceId": document.document_id,
            "documentId": document.document_id,
            "chunkId": str(item.get("chunk_id")),
            "title": document.title,
            "content": str(item.get("content") or document.content),
            "contentHash": str(item.get("text_hash") or document.text_hash),
            "source": document.source,
            "sourceLocator": document.source_locator,
            "sourceReviewStatus": document.source_review_status,
            "licenseStatus": document.license_status,
            "approvalStatus": document.source_review_status,
        }
        for item in selected
    ]


def _question(term: str, scenario_type: str, difficulty: str) -> str:
    if scenario_type == "A_CONCEPT_EXPLANATION":
        if difficulty == "easy":
            return f"경제·금융에서 ‘{term}’이(가) 무엇인지 초보자에게 설명해 주세요."
        if difficulty == "medium":
            return f"‘{term}’의 핵심 의미와 경제적 맥락을 근거를 들어 설명해 주세요."
            return (
                f"‘{term}’의 정의와 구성 요소 사이의 관계를 자료에 근거해 "
                "설명하고, 적용 시 주의할 점도 알려 주세요."
            )
    if scenario_type == "B_MISCONCEPTION_DIAGNOSIS":
        return (
            f"학생이 ‘{term}’에 대해 잘못 이해한 것 같습니다. "
            "한 번의 답변만으로 단정하지 않고 무엇을 확인한 뒤 "
            "어떻게 교정할지 설명해 주세요."
        )
    if scenario_type == "C_PERSONALIZED_LEARNING":
        return (
            f"‘{term}’을(를) 최근 자주 틀린 학습자에게 현재 수준에 맞춰 "
            "설명하고, 이해 여부를 확인할 짧은 질문을 함께 제시해 주세요."
        )
    if scenario_type == "D_MULTITURN_CONTEXT":
        return (
            f"앞선 대화의 맥락을 유지하면서 ‘{term}’을(를) 이 사례에 "
            "적용하면 무엇을 확인해야 하는지 설명해 주세요."
        )
    return (
        f"제공된 자료만으로 ‘{term}’에 관한 미래 수치나 개인별 결과까지 "
        "단정할 수 있는지, 부족한 근거와 추가로 필요한 정보를 구분해 주세요."
    )


def _profile(index: int, term: str, scenario_type: str) -> dict[str, Any]:
    profiles = (
        {
            "accuracyRate": 0.42,
            "recentIncorrectCount": 3,
            "estimatedMastery": 0.35,
            "weaknessScore": 0.76,
            "learningPreference": "plain_definition",
        },
        {
            "accuracyRate": 0.58,
            "recentIncorrectCount": 2,
            "estimatedMastery": 0.52,
            "weaknessScore": 0.55,
            "learningPreference": "worked_example",
        },
        {
            "accuracyRate": 0.76,
            "recentIncorrectCount": 1,
            "estimatedMastery": 0.71,
            "weaknessScore": 0.31,
            "learningPreference": "comparison",
        },
    )
    profile = dict(profiles[index % len(profiles)])
    profile["focusConcept"] = term
    profile["signalStatus"] = "BACKEND_SIGNAL_NOT_FINAL_DIAGNOSIS"
    if scenario_type == "B_MISCONCEPTION_DIAGNOSIS":
        profile["diagnosisPolicy"] = "UNCONFIRMED_UNTIL_REPEATED_EVIDENCE"
    return profile


def _history(term: str, scenario_type: str, difficulty: str) -> list[dict[str, Any]]:
    if scenario_type != "D_MULTITURN_CONTEXT":
        return []
    messages = [
        ("USER", "경제·금융 개념을 공부하고 있어요."),
        ("ASSISTANT", "검수된 학습자료를 근거로 핵심 개념부터 확인해 보겠습니다."),
        ("USER", f"‘{term}’이라는 용어가 나왔는데 먼저 무엇을 뜻하나요?"),
        (
            "ASSISTANT",
            "정의와 자료의 범위를 먼저 구분한 뒤 다음 질문으로 이어가겠습니다.",
        ),
        ("USER", "그 정의에서 가장 중요한 구성 요소는 무엇인가요?"),
        ("ASSISTANT", "앞서 확인한 개념과 근거 문장을 연결해 보겠습니다."),
        ("USER", "비슷해 보이는 경제 용어와는 어떻게 구분하나요?"),
        ("ASSISTANT", "혼동하기 쉬운 관계는 자료에 있는 표현만으로 비교하겠습니다."),
        (
            "USER",
            f"그럼 앞서 설명한 ‘{term}’을(를) 실제 사례에 적용할 때 "
            "무엇을 조심해야 하나요?",
        ),
        (
            "ASSISTANT",
            f"난이도 {difficulty} 수준에 맞춰 적용 조건과 근거의 한계를 "
            "확인하겠습니다.",
        ),
    ]
    return [
        {"sequenceNo": index, "role": role, "content": content}
        for index, (role, content) in enumerate(messages, start=1)
    ]


def _misconception(term: str, misconception_type: str) -> dict[str, Any]:
    claims = {
        "KNOWLEDGE_GAP": f"‘{term}’의 정의와 핵심 구성 요소를 충분히 구분하지 못함",
        "RELATION_ERROR": f"‘{term}’과 관련 용어가 항상 같은 뜻이라고 봄",
        "CAUSAL_ERROR": (
            f"‘{term}’의 변화가 모든 결과를 단방향으로 즉시 결정한다고 단정함"
        ),
        "APPLICATION_ERROR": (
            f"‘{term}’의 정의를 조건 확인 없이 모든 개인 사례에 적용함"
        ),
        "UNCERTAIN": (
            f"현재 한 번의 응답만으로 ‘{term}’에 대한 오개념 여부를 확정할 수 없음"
        ),
    }
    return {
        "type": misconception_type,
        "status": "UNCONFIRMED",
        "claim": claims[misconception_type],
        "confirmationRule": (
            "추가 질문 또는 반복된 학습 증거 없이 오개념을 확정하지 않음"
        ),
    }


def _teaching_behavior(scenario_type: str) -> list[str]:
    behaviors = {
        "A_CONCEPT_EXPLANATION": [
            "define_from_evidence",
            "use_plain_language",
            "cite_source",
        ],
        "B_MISCONCEPTION_DIAGNOSIS": [
            "keep_hypothesis_unconfirmed",
            "ask_follow_up",
            "correct_with_evidence",
        ],
        "C_PERSONALIZED_LEARNING": [
            "adapt_to_profile_signal",
            "use_scaffolded_example",
            "check_understanding",
        ],
        "D_MULTITURN_CONTEXT": [
            "resolve_follow_up_reference",
            "preserve_conversation_context",
            "bound_context",
        ],
        "E_INSUFFICIENT_EVIDENCE": [
            "state_evidence_limit",
            "avoid_invented_values",
            "request_missing_context",
        ],
    }
    return behaviors[scenario_type]


def _validate_history(row: dict[str, Any], row_index: int, errors: list[str]) -> None:
    history = row.get("conversationHistory")
    if not isinstance(history, list):
        errors.append(f"row {row_index} conversationHistory must be a list")
        return
    sequences = [item.get("sequenceNo") for item in history if isinstance(item, dict)]
    if sequences != list(range(1, len(sequences) + 1)):
        errors.append(
            f"row {row_index} conversationHistory sequenceNo is not contiguous"
        )
    if (
        row.get("scenarioType") == "D_MULTITURN_CONTEXT"
        and not 10 <= len(history) <= 20
    ):
        errors.append(f"row {row_index} multi-turn history must contain 5-10 turns")


def _validate_evidence(
    row: dict[str, Any],
    row_index: int,
    documents: dict[str, NormalizedDocument],
    errors: list[str],
) -> None:
    for field in ("approvedEvidence", "evidenceCandidates"):
        evidence = row.get(field, [])
        if not isinstance(evidence, list):
            errors.append(f"row {row_index} {field} must be a list")
            continue
        for item in evidence:
            source_id = item.get("sourceId") if isinstance(item, dict) else None
            document = documents.get(source_id)
            if document is None:
                errors.append(
                    f"row {row_index} {field} has unknown sourceId {source_id}"
                )
                continue
            if not str(item.get("content", "")).strip():
                errors.append(f"row {row_index} {field} has empty content")
            if field == "approvedEvidence" and item.get("approvalStatus") != "approved":
                errors.append(
                    f"row {row_index} approvedEvidence contains non-approved evidence"
                )


def _privacy_findings(value: Any, path: str = "") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            key_path = f"{path}.{key}" if path else key
            normalized = str(key).casefold().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                findings.append(key_path)
            findings.extend(_privacy_findings(child, key_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(_privacy_findings(child, f"{path}[{index}]"))
    elif isinstance(value, str):
        normalized_path = path.casefold()
        is_identifier = any(
            token in normalized_path for token in ("id", "hash", "chunk")
        )
        if not is_identifier and (
            EMAIL_PATTERN.search(value) or PHONE_PATTERN.search(value)
        ):
            findings.append(path)
    return findings


def _shuffled_slots(counts: dict[str, int], rng) -> list[str]:
    values = [key for key, count in counts.items() for _ in range(count)]
    rng.shuffle(values)
    return values


def _unique_content_documents(
    documents: Sequence[NormalizedDocument],
) -> list[NormalizedDocument]:
    seen: set[str] = set()
    selected: list[NormalizedDocument] = []
    for document in documents:
        if document.text_hash in seen:
            continue
        seen.add(document.text_hash)
        selected.append(document)
    return selected


def _doc_key(document: NormalizedDocument) -> tuple[str, str]:
    return document.document_id, document.title


def _duplicates(values: Iterable[str]) -> set[str]:
    counts = Counter(values)
    return {value for value, count in counts.items() if count > 1}


def _term(title: str) -> str:
    return " ".join(title.splitlines()[0].split())[:120]
