from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import IndexConfigurationError
from app.db.models import RAGChunk, RAGDocument, RAGIndexConfiguration


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

    async def chunk_ids_for_documents(self, document_ids: Iterable[str]) -> list[str]:
        values = list(document_ids)
        if not values:
            return []
        result = await self.session.execute(
            select(RAGChunk.chunk_id).where(RAGChunk.document_id.in_(values))
        )
        return list(result.scalars().all())

    async def ensure_index_configuration(
        self,
        collection_name: str,
        embedding_provider: str,
        embedding_model: str,
        embedding_dimension: int,
    ) -> None:
        configuration = await self.session.get(RAGIndexConfiguration, collection_name)
        if configuration is None:
            self.session.add(
                RAGIndexConfiguration(
                    collection_name=collection_name,
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                    embedding_dimension=embedding_dimension,
                )
            )
            await self.session.commit()
            return
        actual = (
            configuration.embedding_provider,
            configuration.embedding_model,
            configuration.embedding_dimension,
        )
        expected = (embedding_provider, embedding_model, embedding_dimension)
        if actual != expected:
            raise IndexConfigurationError(
                "embedding configuration does not match existing collection "
                f"{collection_name!r}: stored={actual}, configured={expected}. "
                "Use a new VECTOR_STORE_COLLECTION or migrate/reindex explicitly."
            )

    async def save_documents(self, documents, nodes, embedding_dimension: int) -> None:
        """Upsert document/chunk metadata after the LlamaIndex insert succeeds."""
        try:
            nodes_by_document: dict[str, list] = {}
            for node in nodes:
                document_id = str(
                    (node.metadata or {}).get("document_id", "unknown-document")
                )
                nodes_by_document.setdefault(document_id, []).append(node)

            for document in documents:
                existing = await self.session.get(RAGDocument, document.document_id)
                if existing is None:
                    existing = RAGDocument(
                        document_id=document.document_id,
                        source_id=document.source_id,
                        title=document.title,
                        source=document.source,
                        source_url=document.source_url,
                        version=document.version,
                        concept_id=document.concept_id,
                        stage_id=document.stage_id,
                        review_status=document.review_status,
                        published_at=document.published_at,
                        updated_at=document.updated_at,
                        license=document.license,
                        content_hash=document.content_hash,
                        metadata_json=document.metadata,
                    )
                    self.session.add(existing)
                else:
                    existing.title = document.title
                    existing.source_id = document.source_id
                    existing.source = document.source
                    existing.source_url = document.source_url
                    existing.version = document.version
                    existing.concept_id = document.concept_id
                    existing.stage_id = document.stage_id
                    existing.review_status = document.review_status
                    existing.published_at = document.published_at
                    existing.updated_at = document.updated_at
                    existing.license = document.license
                    existing.content_hash = document.content_hash
                    existing.metadata_json = document.metadata
                    await self.session.execute(
                        delete(RAGChunk).where(
                            RAGChunk.document_id == document.document_id
                        )
                    )

                for node in nodes_by_document.get(document.document_id, []):
                    metadata = node.metadata or {}
                    self.session.add(
                        RAGChunk(
                            document_id=document.document_id,
                            chunk_id=str(metadata.get("chunk_id", node.node_id)),
                            content=node.get_content(),
                            # LlamaIndex PGVectorStore is the single vector owner.
                            # This application table is an audit/metadata registry.
                            embedding=None,
                            metadata_json=metadata,
                        )
                    )
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
