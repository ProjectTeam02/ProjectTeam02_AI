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
from app.ingestion.document_loader import discover_documents, load_manifest
from app.rag.llamaindex.indexer import DocumentIndexer


async def run(
    path: Path,
    source: str,
    version: str | None,
    manifest: Path | None = None,
    review_status: str = "draft",
    source_id: str | None = None,
    source_url: str | None = None,
    license_name: str | None = None,
    concept_id: str | None = None,
    stage_id: str | None = None,
) -> int:
    documents = (
        load_manifest(manifest)
        if manifest
        else discover_documents(
            path,
            source,
            version,
            review_status,
            source_id,
            source_url,
            license_name,
            concept_id,
            stage_id,
        )
    )
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
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--review-status", default="draft")
    parser.add_argument("--source-id", default=None)
    parser.add_argument("--source-url", default=None)
    parser.add_argument("--license", dest="license_name", default=None)
    parser.add_argument("--concept-id", default=None)
    parser.add_argument("--stage-id", default=None)
    args = parser.parse_args()
    asyncio.run(
        run(
            args.path,
            args.source,
            args.version,
            manifest=args.manifest,
            review_status=args.review_status,
            source_id=args.source_id,
            source_url=args.source_url,
            license_name=args.license_name,
            concept_id=args.concept_id,
            stage_id=args.stage_id,
        )
    )


if __name__ == "__main__":
    main()
