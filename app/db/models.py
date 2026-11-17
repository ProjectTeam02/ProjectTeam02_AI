# 파일 역할: PostgreSQL 연결과 SQLAlchemy 데이터 모델을 관리합니다.
import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


# DB 구조의 기준은 백엔드 레포 database/sql/init/02~04
# (ai 스키마, 소유자 ai_user). 여기 모델은 그 테이블을 읽고 쓰기 위한 매핑이며,
# 구조를 바꿀 때는 백엔드 SQL을 먼저 바꾼다.
# 대화·메시지·근거·장기 메모리는 백엔드(tutor 스키마) 소유라 모델을 두지 않는다.
# 벡터는 LlamaIndex 테이블 ai.data_<컬렉션>에만 저장한다.
class Base(DeclarativeBase):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    pass


class RAGDocument(Base):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    __tablename__ = "rag_documents"

    document_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    source: Mapped[str] = mapped_column(String(1000), nullable=False)
    source_url: Mapped[str | None] = mapped_column(String(2000))
    version: Mapped[str | None] = mapped_column(String(100))
    concept_id: Mapped[str | None] = mapped_column(String(255), index=True)
    stage_id: Mapped[str | None] = mapped_column(String(255), index=True)
    review_status: Mapped[str] = mapped_column(
        String(30), index=True, default="approved", server_default="approved"
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    license: Mapped[str | None] = mapped_column(String(255))
    content_hash: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    chunks: Mapped[list["RAGChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="RAGChunk.chunk_id",
    )


class RAGChunk(Base):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    __tablename__ = "rag_document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_id", name="uq_rag_document_chunk"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    document_id: Mapped[str] = mapped_column(
        String(255),
        ForeignKey("rag_documents.document_id", ondelete="CASCADE"),
        index=True,
    )
    chunk_id: Mapped[str] = mapped_column(String(255), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    document: Mapped[RAGDocument] = relationship(back_populates="chunks")


class RAGIndexConfiguration(Base):
    # 클래스 역할: 관련 상태와 동작을 하나의 객체로 묶습니다.
    __tablename__ = "rag_index_configurations"

    collection_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    embedding_provider: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(255), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
