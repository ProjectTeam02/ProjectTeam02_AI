"""Gold 검수 준비 키트 테스트.

모든 fixture는 이 파일 안에서 만든 **합성 데이터**입니다. 실제 KDI·BOK 원문이나
사람 검수 결과가 아니며, 어떤 테스트도 승인 값을 생성하지 않는지 확인합니다.
"""

from __future__ import annotations

import csv
import json
from collections import Counter

import pytest

from app.evaluation import gold_review_kit as kit
from scripts import gold_review_kit as cli


def _items(n: int, dataset: str = "PRECISION_320") -> list[dict[str, str]]:
    return [
        {
            "dataset": dataset,
            "item_id": f"SYN-{i:03d}",
            "source": "KDI" if i % 2 else "BOK",
        }
        for i in range(n)
    ]


def test_assignment_gives_two_distinct_reviewers_and_balances_load():
    rows = kit.build_assignment_rows(_items(30), ["R1", "R2", "R3"])
    assert len(rows) == 30
    assert all(row["reviewer_1"] != row["reviewer_2"] for row in rows)
    assert {row["assignment_status"] for row in rows} == {"ASSIGNED_NOT_REVIEWED"}
    load = Counter()
    for row in rows:
        load[row["reviewer_1"]] += 1
        load[row["reviewer_2"]] += 1
    assert set(load.values()) == {20}  # 30건 × 2명 / 3명


def test_assignment_defaults_to_placeholders_and_is_deterministic():
    first = kit.build_assignment_rows(_items(5))
    second = kit.build_assignment_rows(list(reversed(_items(5))))
    assert first == second
    assert {(r["reviewer_1"], r["reviewer_2"]) for r in first} == {
        ("REVIEWER_A", "REVIEWER_B")
    }


@pytest.mark.parametrize("reviewers", [["ONLY"], ["A", "A"]])
def test_assignment_rejects_invalid_reviewer_lists(reviewers):
    with pytest.raises(ValueError):
        kit.build_assignment_rows(_items(2), reviewers)


def test_assignment_rejects_duplicate_items():
    with pytest.raises(ValueError):
        kit.build_assignment_rows(_items(2) + _items(1))


def test_cohen_kappa_known_values():
    assert kit.cohen_kappa(["1", "0", "1", "0"], ["1", "0", "1", "0"]) == pytest.approx(
        1.0
    )
    # po=0.5, pe=0.5 → 0
    assert kit.cohen_kappa(["1", "1", "0", "0"], ["1", "0", "1", "0"]) == pytest.approx(
        0.0
    )
    # 교과서 예: po=0.7, pe=0.5 → 0.4
    a = ["Y"] * 20 + ["Y"] * 5 + ["N"] * 10 + ["N"] * 15
    b = ["Y"] * 20 + ["N"] * 5 + ["Y"] * 10 + ["N"] * 15
    assert kit.cohen_kappa(a, b) == pytest.approx(0.4)
    assert kit.cohen_kappa(["2", "2"], ["2", "2"]) is None  # pe == 1, 정의 불가
    assert kit.cohen_kappa([], []) is None


def test_agreement_report_flags_disagreements_and_single_reviews():
    events = [
        {
            "review_status": "SINGLE_REVIEWED",
            "document_id": "D1",
            "reviewer_id": "A",
            "relevance_label": "2",
        },
        {
            "review_status": "SINGLE_REVIEWED",
            "document_id": "D1",
            "reviewer_id": "B",
            "relevance_label": "1",
        },
        {
            "review_status": "SINGLE_REVIEWED",
            "document_id": "D2",
            "reviewer_id": "A",
            "relevance_label": "0",
        },
        {
            "review_status": "SINGLE_REVIEWED",
            "document_id": "D2",
            "reviewer_id": "B",
            "relevance_label": "0",
        },
        {
            "review_status": "SINGLE_REVIEWED",
            "document_id": "D3",
            "reviewer_id": "A",
            "relevance_label": "1",
        },
        # 같은 검수자의 수정은 최신 이벤트만 사용
        {
            "review_status": "SINGLE_REVIEWED",
            "document_id": "D2",
            "reviewer_id": "B",
            "relevance_label": "0",
        },
        {"adjudication_status": "ADJUDICATED", "document_id": "D1"},
    ]
    report = kit.agreement_report(
        kit.latest_labels(events, "precision"), ["D1", "D2", "D3", "D4"]
    )
    assert report["disagreement_count"] == 1
    assert report["disagreements"][0]["item_id"] == "D1"
    assert report["awaiting_second_review"] == ["D3"]
    assert report["not_started_count"] == 1
    assert report["pairs"][0]["shared_items"] == 2
    assert report["pairs"][0]["observed_agreement"] == 0.5
    assert report["gold_is_not_auto_approved"] is True


def test_tutor_labels_use_case_review_events_only():
    events = [
        {
            "eventType": "CASE_REVIEW",
            "caseId": "T1",
            "reviewerId": "A",
            "decision": "APPROVE",
        },
        {
            "eventType": "CASE_REVIEW",
            "caseId": "T1",
            "reviewerId": "B",
            "decision": "REJECT",
        },
        {"eventType": "CASE_ADJUDICATION", "caseId": "T1", "decision": "APPROVE"},
    ]
    assert kit.latest_labels(events, "tutor") == {"T1": {"A": "APPROVE", "B": "REJECT"}}


def test_draft_map_proposes_candidates_but_never_approves():
    cases = [
        {
            "caseId": "SYN-T1",
            "sourceIds": ["bok-syn-1"],
            "expectedConcepts": ["합성개념"],
            "goldStatus": "PENDING_REVIEW",
            "evidenceCandidates": [
                {
                    "sourceId": "bok-syn-1",
                    "documentId": "bok-syn-1",
                    "chunkId": "c0",
                    "contentHash": "h",
                    "sourceReviewStatus": "UNKNOWN",
                    "licenseStatus": "UNCONFIRMED",
                }
            ],
        },
        {"caseId": "SYN-T2", "sourceIds": ["kdi-syn-9"], "expectedConcepts": ["없음"]},
    ]
    concepts = [
        {
            "conceptCode": "C9001",
            "title": "합성개념",
            "sourceDocumentIds": ["bok-syn-1"],
        },
        {"conceptCode": "C9002", "title": "다른개념", "sourceDocumentIds": []},
    ]
    sources = [{"concept_code": "C9002", "document_id": "bok-syn-1"}]
    first, second = kit.draft_concept_evidence_map(cases, concepts, sources)
    assert [c["conceptCode"] for c in first["conceptCodeCandidates"]] == [
        "C9001",
        "C9002",
    ]
    assert first["conceptCodeCandidates"][0]["matchedBy"] == [
        "SOURCE_DOCUMENT_LINK",
        "TITLE_EXACT_MATCH",
    ]
    assert first["evidenceCandidates"][0]["approvalBlockers"] == [
        "SOURCE_REVIEW_NOT_APPROVED",
        "LICENSE_NOT_APPROVED",
    ]
    assert first["mappingStatus"] == second["mappingStatus"] == "DRAFT"
    assert first["goldStatusUnchanged"] == "PENDING_REVIEW"
    assert second["conceptCodeCandidates"] == []
    assert "approvedEvidence" not in first and "conceptCode" not in first


def test_draft_map_marks_partial_title_matches_as_weak():
    cases = [
        {"caseId": "SYN-T3", "sourceIds": [], "expectedConcepts": ["기대인플레이션"]}
    ]
    concepts = [
        {"conceptCode": "C9003", "title": "인플레이션", "sourceDocumentIds": []}
    ]
    (draft,) = kit.draft_concept_evidence_map(cases, concepts)
    assert draft["conceptCodeCandidates"] == [
        {"conceptCode": "C9003", "matchedBy": ["TITLE_PARTIAL_MATCH"]}
    ]


def test_curation_gaps_treat_csv_marks_as_unapproved():
    gaps = kit.curation_gaps(
        concepts=[
            {
                "conceptCode": "C1",
                "title": "a",
                "status": "PUBLISHED",
                "reviewedBy": None,
                "sourceDocumentIds": [],
            },
            {
                "conceptCode": "C2",
                "title": "b",
                "reviewedBy": "x",
                "reviewedAt": "2026-11-01",
                "sourceDocumentIds": ["d"],
            },
        ],
        concept_sources=[
            {
                "concept_code": "C1",
                "document_id": "d1",
                "approve": "Y",
                "match_type": "EXACT",
            }
        ],
        prerequisites=[
            {
                "concept_code": "C2",
                "prerequisite_concept_code": "C1",
                "current_status": "PENDING",
                "decision": "APPROVED",
            }
        ],
        documents=[{"document_id": "d1", "title": "t"}],
        document_status={
            "d1": {"source_review_status": "UNKNOWN", "license_status": "UNCONFIRMED"}
        },
    )
    by_type = {gap["asset_type"]: gap for gap in gaps}
    assert set(by_type) == {"CONCEPT", "CONCEPT_SOURCE", "PREREQUISITE", "BOK_DOCUMENT"}
    assert by_type["CONCEPT"]["asset_id"] == "C1"  # C2는 공백 없음
    assert "reviewed_by" in by_type["CONCEPT_SOURCE"]["missing_fields"]
    assert "DB 승인 이력 아님" in by_type["CONCEPT_SOURCE"]["note"]
    assert "미반영" in by_type["PREREQUISITE"]["note"]
    assert "license_review_status" in by_type["BOK_DOCUMENT"]["missing_fields"]
    summary = kit.summarize_gaps(gaps)
    assert summary["CONCEPT"]["rows_with_gap"] == 1


def _write_queue(path, statuses):
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "document_id",
        "content_hash",
        "source",
        "split",
        "title",
        "content",
        "gold_set_status",
        "review_status",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for i, status in enumerate(statuses):
            writer.writerow(
                {
                    "document_id": f"SYN-{i}",
                    "content_hash": f"h{i}",
                    "source": "KDI",
                    "split": "test",
                    "title": "합성",
                    "content": "합성 본문",
                    "gold_set_status": status,
                    "review_status": "PENDING",
                }
            )


def test_evaluate_is_not_ready_when_zero_approved(tmp_path, capsys):
    _write_queue(tmp_path / cli.PRECISION_QUEUE, ["PENDING_INDEPENDENT_REVIEW"] * 3)
    code = cli.main(
        [
            "--data-dir",
            str(tmp_path),
            "evaluate",
            "--gold-output",
            str(tmp_path / "gold.csv"),
            "--status-output",
            str(tmp_path / "status.json"),
        ]
    )
    assert code == cli.NOT_READY_EXIT
    assert "승인 0건" in capsys.readouterr().err
    assert not (tmp_path / "gold.csv").exists()


def test_evaluate_is_not_ready_when_queue_missing(tmp_path):
    assert cli.main(["--data-dir", str(tmp_path), "evaluate"]) == cli.NOT_READY_EXIT


def test_assign_cli_covers_both_datasets(tmp_path):
    _write_queue(tmp_path / cli.PRECISION_QUEUE, ["PENDING_INDEPENDENT_REVIEW"] * 4)
    cases = tmp_path / cli.TUTOR_CASES
    cases.parent.mkdir(parents=True, exist_ok=True)
    cases.write_text(
        "".join(json.dumps({"caseId": f"SYN-T{i}"}) + "\n" for i in range(2)),
        encoding="utf-8",
    )
    out = tmp_path / "sheet.csv"
    assert cli.main(["--data-dir", str(tmp_path), "assign", "--output", str(out)]) == 0
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig")))
    assert Counter(r["dataset"] for r in rows) == {"PRECISION_320": 4, "TUTOR_100": 2}
