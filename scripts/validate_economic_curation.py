#!/usr/bin/env python3
"""Validate the supplied 2026-11-23 concept/source/prerequisite exports."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.curation.validation import render_report, validate_curation


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=Path("data/curation/2026-11-23"))
    parser.add_argument(
        "--json",
        type=Path,
        default=Path("reports/curation_2026-11-23_validation.json"),
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=Path("reports/curation_2026-11-23_validation.md"),
    )
    args = parser.parse_args()
    result = validate_curation(args.input)
    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(render_report(result), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "READY" else 2


if __name__ == "__main__":
    raise SystemExit(main())
