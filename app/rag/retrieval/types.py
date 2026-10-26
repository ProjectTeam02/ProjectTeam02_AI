from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RetrievedDocument:
    content: str
    source: str
    score: float | None = None
    document_id: str = "unknown-document"
    chunk_id: str = "unknown-chunk"
    title: str | None = None
    version: str | None = None
    source_id: str | None = None
    source_url: str | None = None
    concept_id: str | None = None
    stage_id: str | None = None
    review_status: str = "approved"
    license: str | None = None
    published_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    content_hash: str | None = None

    def citation_key(self) -> tuple[str, str]:
        return self.document_id, self.chunk_id
