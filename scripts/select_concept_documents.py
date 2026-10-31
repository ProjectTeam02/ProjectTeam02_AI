"""Select C0704 candidate documents from supplied local JSONL only.

The output is a human review queue.  It is never an approval or an index
manifest, and documents in ``terms_needs_review.jsonl`` are never merged into
the candidate input.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

from app.ingestion.mentor_dataset import (
    inspect_terms_dataset,
    read_terms_for_candidates,
    select_c0704_candidates,
)


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
    parser.add_argument("--output-dir", type=Path, default=Path("outputs/c0704"))
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report = inspect_terms_dataset(args.approved, args.needs_review)
    if report.status == "NOT_AVAILABLE":
        status = {
            "status": "NOT_AVAILABLE",
            "concept_code": "C0704",
            "mapping_status": "NOT_GENERATED",
            "reason": (
                "required mentor dataset files are not present; no substitute "
                "dataset was used"
            ),
            "dataset_report": report.as_dict(),
            "llm_classification": "NOT_RUN",
            "gold_labels": "NOT_AVAILABLE",
        }
        (args.output_dir / "evaluation_status.json").write_text(
            json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return

    rows = read_terms_for_candidates(args.approved)
    candidates = select_c0704_candidates(rows)
    with (args.output_dir / "mapping_candidates.jsonl").open(
        "w", encoding="utf-8"
    ) as handle:
        for candidate in candidates:
            handle.write(json.dumps(candidate, ensure_ascii=False) + "\n")
    with (args.output_dir / "review_queue.csv").open(
        "w", newline="", encoding="utf-8"
    ) as handle:
        fields = (
            "concept_code",
            "document_id",
            "source_type",
            "term",
            "relevance_score",
            "classification_reason",
            "review_status",
            "reviewer",
            "reviewed_at",
        )
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow({field: candidate.get(field) for field in fields})
    status = {
        "status": "CANDIDATES_READY",
        "concept_code": "C0704",
        "candidate_count": len(candidates),
        "direct_count": sum(
            item["classification_label"] == "DIRECT" for item in candidates
        ),
        "indirect_count": sum(
            item["classification_label"] == "INDIRECT" for item in candidates
        ),
        "exclude_count": sum(
            item["classification_label"] == "EXCLUDE" for item in candidates
        ),
        "mapping_status": "PENDING_HUMAN_REVIEW",
        "llm_classification": "NOT_RUN",
        "gold_labels": "NOT_AVAILABLE",
        "dataset_report": report.as_dict(),
    }
    (args.output_dir / "evaluation_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(status, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
