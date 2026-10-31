"""Validate the mentor terms JSONL files without modifying them."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.question_generation.dataset import inspect_terms_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--approved",
        type=Path,
        default=Path("data/mentor_dataset/terms_approved.jsonl"),
    )
    parser.add_argument(
        "--needs-review",
        type=Path,
        default=Path("data/mentor_dataset/terms_needs_review.jsonl"),
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = inspect_terms_dataset(args.approved, args.needs_review).as_dict()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
