from dataclasses import dataclass


@dataclass(slots=True)
class RetrievedDocument:
    content: str
    source: str
    score: float | None = None
    document_id: str = "unknown-document"
    chunk_id: str = "unknown-chunk"
    title: str | None = None
    version: str | None = None

    def citation_key(self) -> tuple[str, str]:
        return self.document_id, self.chunk_id
