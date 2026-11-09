from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import pytest

from app.dataset_pipeline import gold_review
from scripts import assemble_independent_gold, gold_review_cli


def _template(
    document_id: str = "doc-1",
    split: str = "development",
    content_hash: str = "hash-1",
) -> dict[str, str]:
    return {
        "document_id": document_id,
        "chunk_id": f"KDI:{document_id}:chunk-0000",
        "source": "KDI",
        "title": "물가 상승",
        "content": "물가 상승은 인플레이션의 대표적인 현상이다.",
        "content_hash": content_hash,
        "chapter_id": "inflation",
        "dataset_version": "dataset-v1",
        "rubric_version": "rubric-v1",
        "sampling_bucket": "keyword_candidate",
        "split": split,
    }


def test_single_review_is_saved_without_final_gold() -> None:
    row = _template()
    event = gold_review.create_review_event(
        row,
        reviewer_id="reviewer-a",
        relevance_label="2",
        evidence_quote="물가 상승은 인플레이션의 대표적인 현상이다.",
        reason="인플레이션의 핵심 개념을 직접 설명한다.",
        rubric_version="rubric-v1",
    )

    assert event["review_status"] == "SINGLE_REVIEWED"
    assert event["final_gold_label"] == ""
    assert event["adjudication_status"] == "PENDING"
    assert event["source_review_status"] == "PENDING"
    assert event["license_review_status"] == "PENDING"
    assert event["quiz_suitability"] == "PENDING"


def test_evidence_must_exist_in_original_content() -> None:
    with pytest.raises(ValueError, match="evidence_quote_not_found"):
        gold_review.create_review_event(
            _template(),
            "reviewer-a",
            "2",
            "원문에 없는 문장",
            "근거를 확인할 수 없다.",
            "rubric-v1",
        )


def test_two_reviewers_can_be_adjudicated_without_overwriting_history() -> None:
    row = _template()
    first = gold_review.create_review_event(
        row,
        "reviewer-a",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "직접 관련",
        "rubric-v1",
    )
    second = gold_review.create_review_event(
        row,
        "reviewer-b",
        "1",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "관련 배경 개념",
        "rubric-v1",
    )
    adjudication = gold_review.create_adjudication_event(
        row,
        "adjudicator",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "본문이 챕터 핵심 개념을 직접 설명하므로 2점으로 합의",
        2,
        "ADJUDICATED_CONSENSUS",
        [first, second],
    )

    events = [first, second, adjudication]
    assert len(gold_review.latest_reviewer_events(events)) == 2
    assert gold_review.latest_adjudications(events)["doc-1"]["final_gold_label"] == "2"
    projected = gold_review.build_gold_template_rows([row], events)[0]
    assert projected["gold_set_status"] == "INDEPENDENT_APPROVED"
    assert projected["review_status"] == "APPROVED"
    assert projected["final_gold"] == "2"


def test_adjudication_requires_independent_reviewers() -> None:
    row = _template()
    first = gold_review.create_review_event(
        row,
        "reviewer-a",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "직접 관련",
        "rubric-v1",
    )
    with pytest.raises(ValueError, match="독립 검수자"):
        gold_review.create_adjudication_event(
            row,
            "adjudicator",
            "2",
            "물가 상승은 인플레이션의 대표적인 현상이다.",
            "합의 근거",
            1,
            "ADJUDICATED_CONSENSUS",
            [first],
        )


def test_validation_blocks_evidence_hash_and_split_leakage() -> None:
    development = _template("doc-dev", "development", "same-hash")
    test = _template("doc-test", "test", "same-hash")
    event = gold_review.create_review_event(
        development,
        "reviewer-a",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "직접 관련",
        "rubric-v1",
    )
    tampered = dict(event)
    tampered["content_hash"] = "changed-hash"
    tampered["evidence_quote"] = "원문에 없는 근거"
    tampered["dataset_version"] = "different-dataset"
    result = gold_review.validate_history([development, test], [tampered])
    error_types = {error["type"] for error in result["errors"]}

    assert result["status"] == "FAIL"
    assert "content_hash_mismatch" in error_types
    assert "evidence_not_in_original" in error_types
    assert "dataset_version_mismatch" in error_types
    assert "development_test_content_hash_leakage" in error_types
    duplicate_result = gold_review.validate_history(
        [development, dict(development)], []
    )
    assert any(
        error["type"] == "duplicate_document_id" for error in duplicate_result["errors"]
    )


def test_history_can_be_appended_and_reloaded(tmp_path: Path) -> None:
    row = _template()
    event = gold_review.create_review_event(
        row,
        "reviewer-a",
        "NEEDS_REVIEW",
        "",
        "원문이 부족하여 판단 보류",
        "rubric-v1",
    )
    history_path = tmp_path / "history.jsonl"
    gold_review.append_event(history_path, event)
    loaded = gold_review.load_history(history_path)

    assert loaded == [event]
    assert (
        json.loads(history_path.read_text(encoding="utf-8"))["reviewer_id"]
        == "reviewer-a"
    )


def test_disagreement_report_requires_adjudication() -> None:
    row = _template()
    first = gold_review.create_review_event(
        row,
        "reviewer-a",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "직접 관련",
        "rubric-v1",
    )
    second = gold_review.create_review_event(
        row,
        "reviewer-b",
        "0",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "챕터와 무관",
        "rubric-v1",
    )
    report = gold_review.disagreement_report([row], [first, second])

    assert report["disagreement_count"] == 1
    assert report["items"][0]["labels"] == ["0", "2"]
    assert report["items"][0]["adjudication_required"] is True


def _write_template(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(_template().keys())
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _cli_args(tmp_path: Path, reviewer_id: str) -> argparse.Namespace:
    return argparse.Namespace(
        reviewer_id=reviewer_id,
        source="ALL",
        split="ALL",
        document_id=None,
        adjudicate=False,
        include_reviewed=False,
        validate_only=False,
        rubric_version="rubric-v1",
        kdi=tmp_path / "kdi.csv",
        bok=tmp_path / "bok.csv",
        history=tmp_path / "history.jsonl",
        export_csv=tmp_path / "current.csv",
        export_jsonl=tmp_path / "current.jsonl",
        status=tmp_path / "status.json",
        disagreements=tmp_path / "disagreements.json",
    )


def test_cli_saves_resume_and_prevents_duplicate_for_same_reviewer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _template()
    _write_template(tmp_path / "kdi.csv", [row])
    _write_template(tmp_path / "bok.csv", [])
    answers = iter(
        [
            "2",
            "직접 관련",
            "물가 상승은 인플레이션의 대표적인 현상이다.",
            "",
            "",
            "",
            "q",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    result = gold_review_cli.run(_cli_args(tmp_path, "reviewer-a"))
    events = gold_review.load_history(tmp_path / "history.jsonl")
    assert result["status"] == "PASS"
    assert len(events) == 1
    assert events[0]["source_review_status"] == "PENDING"

    gold_review_cli.run(_cli_args(tmp_path, "reviewer-a"))
    assert len(gold_review.load_history(tmp_path / "history.jsonl")) == 1


def test_cli_keeps_reviewer_histories_independent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    row = _template()
    _write_template(tmp_path / "kdi.csv", [row])
    _write_template(tmp_path / "bok.csv", [])
    first_answers = iter(
        [
            "2",
            "직접 관련",
            "물가 상승은 인플레이션의 대표적인 현상이다.",
            "",
            "",
            "",
            "q",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(first_answers))
    gold_review_cli.run(_cli_args(tmp_path, "reviewer-a"))

    second_answers = iter(
        [
            "1",
            "간접 관련",
            "물가 상승은 인플레이션의 대표적인 현상이다.",
            "",
            "",
            "",
            "q",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _prompt: next(second_answers))
    gold_review_cli.run(_cli_args(tmp_path, "reviewer-b"))
    events = gold_review.load_history(tmp_path / "history.jsonl")
    report = gold_review.disagreement_report([row], events)

    assert {event["reviewer_id"] for event in events} == {
        "reviewer-a",
        "reviewer-b",
    }
    assert report["disagreement_count"] == 1


def test_assembly_requires_consensus_and_rejects_hash_mismatch(tmp_path: Path) -> None:
    row = _template(split="test")
    _write_template(tmp_path / "kdi.csv", [row])
    _write_template(tmp_path / "bok.csv", [])
    first = gold_review.create_review_event(
        row,
        "reviewer-a",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "직접 관련",
        "rubric-v1",
    )
    second = gold_review.create_review_event(
        row,
        "reviewer-b",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "직접 관련",
        "rubric-v1",
    )
    history = tmp_path / "history.jsonl"
    gold_review.append_event(history, first)
    gold_review.append_event(history, second)
    pending = assemble_independent_gold.run(
        tmp_path / "kdi.csv",
        tmp_path / "bok.csv",
        tmp_path / "gold.csv",
        tmp_path / "status.json",
        history,
    )
    assert pending["status"] == "NOT_READY"

    tampered = dict(second)
    tampered["content_hash"] = "different-hash"
    history.write_text(
        "\n".join(json.dumps(event, ensure_ascii=False) for event in [first, tampered])
        + "\n",
        encoding="utf-8",
    )
    rejected = assemble_independent_gold.run(
        tmp_path / "kdi.csv",
        tmp_path / "bok.csv",
        tmp_path / "gold.csv",
        tmp_path / "status-mismatch.json",
        history,
    )
    assert rejected["status"] == "NOT_READY"
    assert rejected["history_validation"]["status"] == "FAIL"


def test_assembly_is_ready_only_after_adjudication(tmp_path: Path) -> None:
    row = _template(split="test")
    _write_template(tmp_path / "kdi.csv", [row])
    _write_template(tmp_path / "bok.csv", [])
    first = gold_review.create_review_event(
        row,
        "reviewer-a",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "직접 관련",
        "rubric-v1",
    )
    second = gold_review.create_review_event(
        row,
        "reviewer-b",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "직접 관련",
        "rubric-v1",
    )
    adjudication = gold_review.create_adjudication_event(
        row,
        "adjudicator",
        "2",
        "물가 상승은 인플레이션의 대표적인 현상이다.",
        "두 평가자가 동일하게 직접 관련으로 판정하여 합의",
        2,
        "ADJUDICATED_CONSENSUS",
        [first, second],
    )
    history = tmp_path / "history.jsonl"
    for event in (first, second, adjudication):
        gold_review.append_event(history, event)

    result = assemble_independent_gold.run(
        tmp_path / "kdi.csv",
        tmp_path / "bok.csv",
        tmp_path / "gold.csv",
        tmp_path / "status.json",
        history,
    )

    assert result["status"] == "READY"
    assert result["gold_values_created_automatically"] is False
    assert (tmp_path / "gold.csv").is_file()
