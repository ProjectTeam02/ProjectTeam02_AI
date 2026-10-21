"""Index approved .txt/.md learning material into LlamaIndex + pgvector.

This script intentionally does not manufacture financial source material. Put
approved documents in ``data/`` and provide stable metadata through the CLI.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.db.postgres import session_factory
from app.db.repositories.rag_repository import RAGDocumentRepository
from app.rag.llamaindex.indexer import DocumentIndexer, IngestDocument


def discover_documents(root: Path, source: str, version: str | None) -> list[IngestDocument]:
    documents = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".txt", ".md"}:
            continue
        content = path.read_text(encoding="utf-8").strip()
        if content:
            documents.append(
                IngestDocument(
                    document_id=path.relative_to(root).as_posix(),
                    title=path.stem,
                    source=source,
                    content=content,
                    version=version,
                )
            )
    return documents


async def run(path: Path, source: str, version: str | None) -> int:
    documents = discover_documents(path, source, version)
    if not documents:
        print(f"No approved .txt/.md documents found under {path}")
        return 0
    async with session_factory() as session:
        indexer = DocumentIndexer(repository=RAGDocumentRepository(session))
        count = await indexer.index(documents)
    print(f"Indexed {count} chunks from {len(documents)} documents")
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=Path("data"))
    parser.add_argument("--source", default="approved-learning-material")
    parser.add_argument("--version", default=None)
    args = parser.parse_args()
    asyncio.run(run(args.path, args.source, args.version))


if __name__ == "__main__":
    main()
