"""Safety policy shared by every retrieval backend."""

from __future__ import annotations

from app.rag.retrieval.types import RetrievedDocument

APPROVED_LICENSE_STATUSES = {"approved", "cleared", "verified"}
BLOCKED_LICENSE_MARKERS = (
    "pending",
    "review",
    "unconfirmed",
    "unknown",
    "require",
    "denied",
    "rejected",
)


def is_retrieval_eligible(
    document: RetrievedDocument,
    approved_review_status: str,
) -> bool:
    """Return whether a document can participate in Verified RAG.

    ``license_review_status`` is optional for backward compatibility with the
    legacy RAG rows. When it is present, only an explicit approved/cleared/
    verified value is accepted. Legacy ``license`` values that clearly state
    a pending or review-required state are blocked as well.
    """

    if document.review_status.casefold() != approved_review_status.casefold():
        return False
    status = (document.license_review_status or "").strip().casefold()
    if status and status not in APPROVED_LICENSE_STATUSES:
        return False
    license_name = (document.license or "").strip().casefold()
    return not any(marker in license_name for marker in BLOCKED_LICENSE_MARKERS)
