from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import RAGChunk, RAGDocument


class RAGDocumentRepository:
    """Persist application-owned document metadata alongside the vector index."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def existing_content_hashes(self, hashes: Iterable[str]) -> set[str]:
        values = list(hashes)
        if not values:
            return set()
        result = await self.session.execute(
            select(RAGDocument.content_hash).where(RAGDocument.content_hash.in_(values))
        )
        return set(result.scalars().all())

    async def save_documents(self, documents, nodes, embedding_dimension: int) -> None:
        """Upsert document/chunk metadata after the LlamaIndex insert succeeds."""
        try:
            nodes_by_document: dict[str, list] = {}
            for node in nodes:
                document_id = str((node.metadata or {}).get("document_id", "unknown-document"))
                nodes_by_document.setdefault(document_id, []).append(node)

            for document in documents:
                existing = await self.session.get(RAGDocument, document.document_id)
                if existing is None:
                    existing = RAGDocument(
                        document_id=document.document_id,
                        title=document.title,
                        source=document.source,
                        version=document.version,
                        content_hash=document.content_hash,
                        metadata_json={},
                    )
                    self.session.add(existing)
                else:
                    existing.title = document.title
                    existing.source = document.source
                    existing.version = document.version
                    existing.content_hash = document.content_hash
                    await self.session.execute(
                        delete(RAGChunk).where(RAGChunk.document_id == document.document_id)
                    )

                for node in nodes_by_document.get(document.document_id, []):
                    metadata = node.metadata or {}
                    embedding = getattr(node, "embedding", None)
                    if embedding is not None and len(embedding) != embedding_dimension:
                        embedding = None
                    self.session.add(
                        RAGChunk(
                            document_id=document.document_id,
                            chunk_id=str(metadata.get("chunk_id", node.node_id)),
                            content=node.get_content(),
                            embedding=embedding,
                            metadata_json=metadata,
                        )
                    )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
