from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class IngestDocument:
    document_id: str
    title: str
    source: str
    content: str
    version: str | None = None
    source_id: str = ""
    source_url: str | None = None
    concept_id: str | None = None
    stage_id: str | None = None
    review_status: str = "approved"
    published_at: datetime | None = None
    updated_at: datetime | None = None
    license: str | None = None
    content_hash: str = ""

    @property
    def metadata(self) -> dict:
        return {
            "source_id": self.source_id,
            "document_id": self.document_id,
            "document_version": self.version or "",
            "title": self.title,
            "source_url": self.source_url or self.source,
            "concept_id": self.concept_id or "",
            "stage_id": self.stage_id or "",
            "review_status": self.review_status,
            "published_at": self.published_at.isoformat() if self.published_at else "",
            "updated_at": self.updated_at.isoformat() if self.updated_at else "",
            "license": self.license or "",
            "content_hash": self.content_hash,
        }


class DocumentIndexer:
    def __init__(
        self, index_manager=None, settings: Settings | None = None, repository=None
    ):
        self.settings = settings or get_settings()
        self.index_manager = index_manager
        self.repository = repository
        self._content_hashes: set[str] = set()

    async def index(
        self, documents: list[IngestDocument | dict], collection: str | None = None
    ) -> int:
        from llama_index.core import Document
        from llama_index.core.node_parser import SentenceSplitter

        normalized = [self._normalize(item) for item in documents]
        rejected = [
            item.document_id
            for item in normalized
            if item.review_status != self.settings.approved_review_status
        ]
        if rejected:
            raise ValueError(
                "only approved documents may be indexed; rejected document_ids="
                + ", ".join(rejected)
            )
        collection_name = collection or self.settings.vector_store_collection
        if self.repository is not None:
            await self.repository.ensure_index_configuration(
                collection_name,
                self.settings.embedding_provider,
                self.settings.embedding_model,
                self.settings.embedding_dimension,
            )
        repository_hashes = set()
        if self.repository is not None:
            repository_hashes = await self.repository.existing_content_hashes(
                [self._content_hash(item.content) for item in normalized]
            )
        new_documents = []
        new_items = []
        for item in normalized:
            content_hash = self._content_hash(item.content)
            if (
                content_hash in self._content_hashes
                or content_hash in repository_hashes
            ):
                continue
            self._content_hashes.add(content_hash)
            item.content_hash = content_hash
            if not item.source_id:
                item.source_id = item.source
            if not item.source_url:
                item.source_url = item.source
            new_items.append(item)
            new_documents.append(
                Document(
                    text=item.content,
                    id_=item.document_id,
                    metadata={
                        **item.metadata,
                        "source": item.source,
                        "version": item.version or "",
                    },
                )
            )
        if not new_documents:
            return 0

        manager = self.index_manager
        if manager is None:
            from app.rag.llamaindex.index_manager import IndexManager

            manager = IndexManager(self.settings)
            self.index_manager = manager
        splitter = SentenceSplitter(
            chunk_size=self.settings.chunk_size,
            chunk_overlap=self.settings.chunk_overlap,
        )
        nodes = splitter.get_nodes_from_documents(new_documents)
        per_document_count: dict[str, int] = {}
        hashes_by_document = {item.document_id: item.content_hash for item in new_items}
        for node in nodes:
            document_id = str(node.metadata.get("document_id", "document"))
            chunk_index = per_document_count.get(document_id, 0)
            per_document_count[document_id] = chunk_index + 1
            content_hash = hashes_by_document[document_id][:12]
            chunk_id = f"{document_id}:{content_hash}:{chunk_index}"
            node.id_ = chunk_id
            node.metadata["chunk_id"] = chunk_id
        index = manager.get_or_create(collection_name)
        old_node_ids: list[str] = []
        if self.repository is not None:
            old_node_ids = await self.repository.chunk_ids_for_documents(
                [item.document_id for item in new_items]
            )
        if old_node_ids:
            await index.vector_store.adelete_nodes(node_ids=old_node_ids)
        await index.ainsert_nodes(nodes)
        if self.repository is not None:
            try:
                await self.repository.save_documents(
                    new_items,
                    nodes,
                    embedding_dimension=self.settings.embedding_dimension,
                )
            except Exception:
                # Compensate for the non-transactional boundary between the
                # LlamaIndex table and the application metadata registry.
                await index.vector_store.adelete_nodes(
                    node_ids=[node.node_id for node in nodes]
                )
                raise
        return len(nodes)

    @staticmethod
    def _content_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    @staticmethod
    def _normalize(item: IngestDocument | dict) -> IngestDocument:
        if isinstance(item, IngestDocument):
            return item
        return IngestDocument(
            document_id=str(item["document_id"]),
            title=str(item.get("title", item["document_id"])),
            source=str(item.get("source", "unknown")),
            content=str(item["content"]),
            version=item.get("document_version", item.get("version")),
            source_id=str(item.get("source_id", item.get("source", "unknown"))),
            source_url=item.get("source_url", item.get("source")),
            concept_id=item.get("concept_id"),
            stage_id=item.get("stage_id"),
            review_status=str(item.get("review_status", "approved")),
            published_at=DocumentIndexer._datetime(item.get("published_at")),
            updated_at=DocumentIndexer._datetime(item.get("updated_at")),
            license=item.get("license"),
        )

    @staticmethod
    def _datetime(value) -> datetime | None:
        if value is None or isinstance(value, datetime):
            return value
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
