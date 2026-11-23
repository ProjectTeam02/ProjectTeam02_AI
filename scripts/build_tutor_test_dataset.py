#!/usr/bin/env python3
"""Build the 100-case tutor evaluation dataset from local canonical sources."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if __package__ in {None, ""}:
    sys.path.insert(0, str(ROOT))

from app.dataset_pipeline.io import load_corpus  # noqa: E402
from app.evaluation.tutor_dataset import (  # noqa: E402
    SEED,
    build_tutor_dataset,
    dataset_manifest,
    validate_tutor_dataset,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data" / "evaluation" / "tutor_test_100.jsonl",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=ROOT / "reports" / "evaluation" / "dataset_manifest.json",
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--force", action="store_true")
    return parser


def load_chunk_index(data_dir: Path) -> dict[str, list[dict]]:
    path = data_dir / "processed" / "chunks.jsonl"
    if not path.is_file():
        return {}
    chunks: dict[str, list[dict]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        chunks.setdefault(str(row.get("document_id")), []).append(row)
    return chunks


def main() -> int:
    args = build_parser().parse_args()
    if args.output.exists() and not args.force:
        raise SystemExit(
            f"refusing to overwrite existing output: {args.output}; use --force"
        )
    documents, corpus_inventory = load_corpus(args.data_dir)
    rows = build_tutor_dataset(
        documents,
        seed=args.seed,
        evidence_chunks=load_chunk_index(args.data_dir),
    )
    validation = validate_tutor_dataset(rows, documents)
    if not validation["valid"]:
        raise SystemExit(json.dumps(validation, ensure_ascii=False, indent=2))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    manifest = dataset_manifest(rows, corpus_inventory, validation, seed=args.seed)
    manifest["generated_at"] = datetime.now(timezone.utc).isoformat()
    manifest["files"] = {
        "scenario_jsonl": str(args.output.relative_to(ROOT)),
        "scenario_sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
        "manifest": str(args.manifest.relative_to(ROOT)),
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {"output": str(args.output), "manifest": str(args.manifest), **validation},
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
