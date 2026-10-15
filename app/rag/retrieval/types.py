from dataclasses import dataclass


@dataclass(slots=True)
class RetrievedDocument:
    content: str
    source: str
    score: float | None = None
