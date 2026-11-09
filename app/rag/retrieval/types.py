# 파일 역할: LlamaIndex 기반 RAG 검색·생성·메모리·인덱싱 기능을 제공합니다.
from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class RetrievedDocument:
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
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
    concept_code: str | None = None
    stage_id: str | None = None
    review_status: str = "approved"
    license: str | None = None
    published_at: datetime | str | None = None
    updated_at: datetime | str | None = None
    content_hash: str | None = None
    term: str | None = None
    term_kr: str | None = None
    term_en: str | None = None
    publisher: str | None = None
    document_name: str | None = None
    edition: str | None = None
    printed_page: int | None = None
    related_terms: list[str] | None = None
    retrieval_method: str = "vector"

    def citation_key(self) -> tuple[str, str]:
        # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
        return self.document_id, self.chunk_id
