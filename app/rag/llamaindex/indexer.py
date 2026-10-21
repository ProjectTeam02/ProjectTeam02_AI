from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass

from app.core.config import Settings, get_settings


@dataclass(slots=True)
class IngestDocument:
    document_id: str
    title: str
    source: str
    content: str
    version: str | None = None
    content_hash: str = ""


class DocumentIndexer:
    def __init__(self, index_manager=None, settings: Settings | None = None, repository=None):
        self.settings = settings or get_settings()
        self.index_manager = index_manager
        self.repository = repository
        self._content_hashes: set[str] = set()

    async def index(self, documents: list[IngestDocument | dict], collection: str | None = None) -> int:
        from llama_index.core import Document
        from llama_index.core.node_parser import SentenceSplitter

        normalized = [self._normalize(item) for item in documents]
        repository_hashes = set()
        if self.repository is not None:
            repository_hashes = await self.repository.existing_content_hashes(
                [self._content_hash(item.content) for item in normalized]
            )
        new_documents = []
        new_items = []
        for item in normalized:
            content_hash = self._content_hash(item.content)
            if content_hash in self._content_hashes or content_hash in repository_hashes:
                continue
            self._content_hashes.add(content_hash)
            item.content_hash = content_hash
            new_items.append(item)
            new_documents.append(
                Document(
                    text=item.content,
                    metadata={
                        "document_id": item.document_id,
                        "title": item.title,
                        "source": item.source,
                        "version": item.version or "",
                        "content_hash": content_hash,
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
            chunk_size=self.settings.chunk_size, chunk_overlap=self.settings.chunk_overlap
        )
        nodes = splitter.get_nodes_from_documents(new_documents)
        for index, node in enumerate(nodes):
            node.metadata.setdefault("chunk_id", f"{node.metadata.get('document_id', 'document')}-{index}")
        index = await asyncio.to_thread(manager.get_or_create, collection)
        await asyncio.to_thread(index.insert_nodes, nodes)
        if self.repository is not None:
            await self.repository.save_documents(
                new_items, nodes, embedding_dimension=self.settings.embedding_dimension
            )
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
            version=item.get("version"),
        )
