import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
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


class Base(DeclarativeBase):
    pass


class AIConversation(Base):
    __tablename__ = "ai_conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    stage_id: Mapped[str | None] = mapped_column(String(255), index=True)
    concept_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="active", server_default="active"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    messages: Mapped[list["AIMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="AIMessage.created_at",
    )


class AIMessage(Base):
    __tablename__ = "ai_messages"
    __table_args__ = (
        UniqueConstraint(
            "conversation_id", "sequence_no", name="uq_ai_message_sequence"
        ),
        UniqueConstraint("request_id", "role", name="uq_ai_message_request_role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ai_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(
        String(20), default="completed", server_default="completed"
    )
    grounded: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    conversation: Mapped[AIConversation] = relationship(back_populates="messages")
    sources: Mapped[list["AIMessageSource"]] = relationship(
        back_populates="message", cascade="all, delete-orphan"
    )


class AIMessageSource(Base):
    __tablename__ = "ai_message_sources"
    __table_args__ = (
        UniqueConstraint(
            "message_id", "document_id", "chunk_id", name="uq_ai_message_source"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ai_messages.id", ondelete="CASCADE"), index=True
    )
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    document_id: Mapped[str] = mapped_column(String(255), nullable=False)
    chunk_id: Mapped[str] = mapped_column(String(255), nullable=False)
    document_version: Mapped[str | None] = mapped_column(String(100))
    title_snapshot: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(2000))
    message: Mapped[AIMessage] = relationship(back_populates="sources")


class AIUserMemory(Base):
    __tablename__ = "ai_user_memories"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class RAGDocument(Base):
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
    embedding: Mapped[list[float] | None] = mapped_column(Vector(1536))
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict, nullable=False)
    document: Mapped[RAGDocument] = relationship(back_populates="chunks")


class RAGIndexConfiguration(Base):
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
