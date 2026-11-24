"""Read-only inspection of the concept/source/prerequisite export bundle."""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

CURATION_FILES = {
    "conceptMaster": "concept/concept_master.json",
    "conceptMaster1123": "concept/concept_master_1123.json",
    "conceptCheck": "concept/concept_check.txt",
    "bokDocumentsRaw": "source/bok_documents_raw.csv",
    "bokDocuments": "source/bok_documents.csv",
    "sourceCandidates": "source/concept_source_candidates.csv",
    "sourceReviewed": "source/concept_sources_reviewed.csv",
    "sourceCheck": "source/source_check.txt",
    "sourceCheckAfter": "source/source_check_after.txt",
    "prerequisiteRaw": "prerequisite/prerequisite_raw.csv",
    "prerequisiteReview": "prerequisite/prerequisite_review.csv",
    "aiSchemaCheck": "db_check/ai_schema_check.txt",
}


def inspect_curation_inputs(
    structured_root: Path,
    *,
    flat_fallback: Path | None = None,
) -> dict[str, Any]:
    structured_missing = [
        relative
        for relative in CURATION_FILES.values()
        if not (structured_root / relative).is_file()
    ]
    root = structured_root
    layout = "structured"
    if structured_missing and flat_fallback is not None:
        flat_missing = [
            Path(relative).name
            for relative in CURATION_FILES.values()
            if not (flat_fallback / Path(relative).name).is_file()
        ]
        if not flat_missing:
            root = flat_fallback
            layout = "flat_legacy"
    report: dict[str, Any] = {
        "status": "BLOCKED" if structured_missing else "READY",
        "layout": layout,
        "requestedRoot": str(structured_root),
        "resolvedRoot": str(root),
        "structuredMissingFiles": structured_missing,
        "counts": {},
        "licenseStatus": {},
        "approvalBoundary": "CSV and text findings are not DB approval",
    }
    if layout == "flat_legacy":
        report["status"] = "BLOCKED"
        report["warning"] = (
            "structured curation directory is absent; flat exports are inspection-only"
        )
    def resolved_path(relative: str) -> Path:
        return root / (relative if layout == "structured" else Path(relative).name)

    if not all(
        resolved_path(relative).is_file() for relative in CURATION_FILES.values()
    ):
        report["errors"] = ["curation exports are incomplete"]
        return report

    concept_payload = json.loads(
        resolved_path(CURATION_FILES["conceptMaster1123"]).read_text(
            encoding="utf-8"
        )
    )
    concepts = concept_payload.get("concepts", [])
    documents = _csv_rows(resolved_path(CURATION_FILES["bokDocuments"]))
    source_reviewed = _csv_rows(resolved_path(CURATION_FILES["sourceReviewed"]))
    prerequisite_review = _csv_rows(
        resolved_path(CURATION_FILES["prerequisiteReview"])
    )
    schema_text = resolved_path(CURATION_FILES["aiSchemaCheck"]).read_text(
        encoding="utf-8-sig"
    )
    source_text = resolved_path(CURATION_FILES["sourceCheckAfter"]).read_text(
        encoding="utf-8-sig"
    )
    report["counts"] = {
        "concepts": len(concepts),
        "bokDocuments": len(documents),
        "sourceReviewedRows": len(source_reviewed),
        "prerequisiteReviewRows": len(prerequisite_review),
        "aiSchemaPasses": len(re.findall(r"\|\s*PASS\s*\|", schema_text)),
    }
    license_counts: dict[str, int] = {}
    for match in re.finditer(
        r"\|\s*(PENDING|APPROVED|REJECTED|UNCONFIRMED)\s*\|\s*(\d+)\s*$",
        schema_text,
        flags=re.IGNORECASE | re.MULTILINE,
    ):
        status = match.group(1).upper()
        license_counts[status] = license_counts.get(status, 0) + int(match.group(2))
    report["licenseStatus"] = license_counts
    report["sourceCheckAfterMentionsPending"] = bool(
        re.search(r"\bPENDING\b", source_text, flags=re.IGNORECASE)
    )
    report["publishedConceptsMissingReviewHistory"] = [
        item.get("conceptCode")
        for item in concepts
        if str(item.get("status", "")).upper() == "PUBLISHED"
        and (not item.get("reviewedBy") or not item.get("reviewedAt"))
    ]
    report["sourceReviewedApprovedRows"] = sum(
        str(row.get("approve", "")).strip().upper() == "APPROVED"
        or str(row.get("decision", "")).strip().upper() == "APPROVED"
        for row in source_reviewed
    )
    report["prerequisiteApprovedRowsAreUntrusted"] = sum(
        str(row.get("decision", "")).strip().upper() == "APPROVED"
        for row in prerequisite_review
    )
    return report


def _csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]
