"""Validate curriculum structure and prerequisite references read-only."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.question_generation.dataset import validate_curriculum


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--path", type=Path, default=Path("data/mentor_dataset/curriculum_full.json")
    )
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    result = validate_curriculum(args.path).as_dict()
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")


if __name__ == "__main__":
    main()
