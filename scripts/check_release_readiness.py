from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON report {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON report must contain an object: {path}")
    return value


def _count(report: dict[str, Any], key: str) -> int:
    quality = report.get("quality_issues", {})
    item = quality.get(key, {}) if isinstance(quality, dict) else {}
    value = item.get("count", 0) if isinstance(item, dict) else 0
    return int(value)


def evaluate_readiness(
    *,
    validation_report: Path,
    gold_status_report: Path,
    chapter_config_report: Path,
) -> dict[str, Any]:
    validation = _load_json(validation_report)
    gold = _load_json(gold_status_report)
    chapter = _load_json(chapter_config_report)

    checks = {
        "source_urls_complete": _count(validation, "bok_source_url_missing") == 0,
        "source_review_resolved": (
            _count(validation, "source_review_status_unresolved") == 0
        ),
        "licenses_confirmed": (
            _count(validation, "license_status_unconfirmed") == 0
        ),
        "independent_gold_ready": gold.get("status") == "READY",
        "canonical_curriculum": chapter.get("curriculum_status") == "CANONICAL",
    }
    blockers = [name for name, passed in checks.items() if not passed]
    return {
        "ready": not blockers,
        "blockers": blockers,
        "checks": checks,
        "observed": {
            "document_count": validation.get("document_count"),
            "gold_status": gold.get("status"),
            "chapter_config_status": chapter.get("curriculum_status"),
            "bok_source_url_missing": _count(
                validation, "bok_source_url_missing"
            ),
            "source_review_status_unresolved": _count(
                validation, "source_review_status_unresolved"
            ),
            "license_status_unconfirmed": _count(
                validation, "license_status_unconfirmed"
            ),
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Fail closed until RAG data and evaluation inputs are release-ready."
        )
    )
    parser.add_argument(
        "--validation-report",
        type=Path,
        default=Path("reports/full_dataset_validation.json"),
    )
    parser.add_argument(
        "--gold-status-report",
        type=Path,
        default=Path("reports/independent_gold_review_status.json"),
    )
    parser.add_argument(
        "--chapter-config-report",
        type=Path,
        default=Path("reports/chapter_config.json"),
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="print blockers without failing the command",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)

    try:
        result = evaluate_readiness(
            validation_report=args.validation_report,
            gold_status_report=args.gold_status_report,
            chapter_config_report=args.chapter_config_report,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        status = "READY" if result["ready"] else "BLOCKED"
        print(f"Release readiness: {status}")
        for name, passed in result["checks"].items():
            print(f"- {'PASS' if passed else 'BLOCK'} {name}")
        if result["blockers"]:
            print("Blockers: " + ", ".join(result["blockers"]))

    return 0 if result["ready"] or args.report_only else 1


if __name__ == "__main__":
    raise SystemExit(main())
