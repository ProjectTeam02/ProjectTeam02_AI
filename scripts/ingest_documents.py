"""Index approved .txt/.md learning material into LlamaIndex + pgvector.

This script intentionally does not manufacture financial source material. Put
approved documents in ``data/`` and provide stable metadata through the CLI.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from app.db.connection import session_factory
from app.rag.indexing.indexer import DocumentIndexer
from app.rag.ingestion.bok_terms_loader import load_bok_terms, validate_bok_dataset
from app.rag.ingestion.document_loader import discover_documents, load_manifest
from app.repositories.rag_repository import RAGDocumentRepository


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
    bok_terms: Path | None = None,
    bok_source: Path | None = None,
) -> int:
    if bok_terms:
        if bok_source is None:
            raise ValueError("--bok-source is required with --bok-terms")
        validation = validate_bok_dataset(bok_source, bok_terms)
        documents = load_bok_terms(bok_terms, approved_only=True)
        print(
            "Validated BOK dataset: "
            f"source={validation.source_count}, rag={validation.rag_count}, "
            f"approved={validation.approved_count}, "
            f"needs_review={validation.review_count} (excluded)"
        )
    else:
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
    parser.add_argument("--bok-terms", type=Path, default=None)
    parser.add_argument("--bok-source", type=Path, default=None)
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
            bok_terms=args.bok_terms,
            bok_source=args.bok_source,
        )
    )


if __name__ == "__main__":
    main()
