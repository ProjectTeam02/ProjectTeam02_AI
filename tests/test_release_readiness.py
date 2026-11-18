import json
from pathlib import Path

from scripts.check_release_readiness import evaluate_readiness, main


def _write(path: Path, value: dict) -> Path:
    path.write_text(json.dumps(value), encoding="utf-8")
    return path


def test_release_readiness_fails_closed_for_current_unresolved_reports(tmp_path):
    validation = _write(
        tmp_path / "validation.json",
        {
            "document_count": 2,
            "quality_issues": {
                "bok_source_url_missing": {"count": 1},
                "source_review_status_unresolved": {"count": 2},
                "license_status_unconfirmed": {"count": 2},
            },
        },
    )
    gold = _write(tmp_path / "gold.json", {"status": "NOT_EVALUATED"})
    chapter = _write(
        tmp_path / "chapter.json", {"curriculum_status": "DRAFT_NOT_CANONICAL"}
    )

    result = evaluate_readiness(
        validation_report=validation,
        gold_status_report=gold,
        chapter_config_report=chapter,
    )

    assert result["ready"] is False
    assert len(result["blockers"]) == 5


def test_release_readiness_accepts_fully_approved_reports(tmp_path):
    validation = _write(
        tmp_path / "validation.json",
        {
            "document_count": 2,
            "quality_issues": {
                "bok_source_url_missing": {"count": 0},
                "source_review_status_unresolved": {"count": 0},
                "license_status_unconfirmed": {"count": 0},
            },
        },
    )
    gold = _write(tmp_path / "gold.json", {"status": "READY"})
    chapter = _write(tmp_path / "chapter.json", {"curriculum_status": "CANONICAL"})

    assert evaluate_readiness(
        validation_report=validation,
        gold_status_report=gold,
        chapter_config_report=chapter,
    )["ready"] is True


def test_report_only_does_not_fail_for_unready_inputs(tmp_path, capsys):
    paths = [
        _write(
            tmp_path / "validation.json",
            {"quality_issues": {"bok_source_url_missing": {"count": 1}}},
        ),
        _write(tmp_path / "gold.json", {"status": "NOT_EVALUATED"}),
        _write(tmp_path / "chapter.json", {"curriculum_status": "DRAFT"}),
    ]
    assert main(
        [
            "--validation-report",
            str(paths[0]),
            "--gold-status-report",
            str(paths[1]),
            "--chapter-config-report",
            str(paths[2]),
            "--report-only",
        ]
    ) == 0
    assert "Release readiness: BLOCKED" in capsys.readouterr().out
