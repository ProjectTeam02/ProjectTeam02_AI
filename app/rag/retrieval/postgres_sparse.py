from __future__ import annotations

from sqlalchemy import bindparam, text

from app.core.config import Settings, get_settings
from app.core.exceptions import RetrievalError
from app.db.connection import session_factory
from app.rag.retrieval.types import RetrievedDocument


class PostgresSparseRetriever:
    """Sparse retrieval over existing RAG tables using PostgreSQL FTS.

    No table or API contract is changed. The query uses the ``simple`` text
    configuration because Korean stemming is not assumed to be installed.
    ``rag_document_chunks.metadata_json`` is used only for metadata owned by
    the existing ingestion/indexing path.
    """

    def __init__(self, settings: Settings | None = None, session_factory_fn=None):
        self.settings = settings or get_settings()
        self._session_factory = session_factory_fn or session_factory

    async def retrieve(
        self,
        query: str,
        top_k: int = 5,
        concept_id: str | None = None,
        stage_id: str | None = None,
        concept_codes: list[str] | None = None,
    ) -> list[RetrievedDocument]:
        if not query.strip():
            return []
        clauses = [
            "d.review_status = :approved_status",
            "to_tsvector('simple', coalesce(c.content, '')) "
            "@@ plainto_tsquery('simple', :query)",
        ]
        params: dict[str, object] = {
            "approved_status": self.settings.approved_review_status,
            "query": query,
            "limit": top_k,
        }
        if concept_id:
            clauses.append("d.concept_id = :concept_id")
            params["concept_id"] = concept_id
        if stage_id:
            clauses.append("d.stage_id = :stage_id")
            params["stage_id"] = stage_id
        if concept_codes:
            clauses.append("c.metadata_json ->> 'concept_code' IN :concept_codes")
            params["concept_codes"] = concept_codes

        statement = text(
            "SELECT c.content, c.document_id, c.chunk_id, c.metadata_json, "
            "d.source, d.source_id, d.source_url, d.title, d.version, "
            "d.concept_id, d.stage_id, d.review_status, d.license, "
            "d.published_at, d.updated_at, "
            "ts_rank_cd(to_tsvector('simple', coalesce(c.content, '')), "
            "plainto_tsquery('simple', :query)) AS sparse_score "
            "FROM rag_document_chunks c "
            "JOIN rag_documents d ON d.document_id = c.document_id "
            f"WHERE {' AND '.join(clauses)} "
            "ORDER BY sparse_score DESC, c.document_id, c.chunk_id "
            "LIMIT :limit"
        )
        if concept_codes:
            statement = statement.bindparams(bindparam("concept_codes", expanding=True))
        try:
            async with self._session_factory() as session:
                result = await session.execute(statement, params)
                return [self._document(row) for row in result.mappings().all()]
        except Exception as exc:
            raise RetrievalError("sparse retrieval failed") from exc

    @staticmethod
    def _document(row) -> RetrievedDocument:
        metadata = row.get("metadata_json") or {}
        return RetrievedDocument(
            content=str(row["content"]),
            source=str(row.get("source") or "unknown"),
            score=float(row["sparse_score"] or 0.0),
            document_id=str(row["document_id"]),
            chunk_id=str(row["chunk_id"]),
            title=row.get("title"),
            version=row.get("version") or metadata.get("document_version"),
            source_id=row.get("source_id"),
            source_url=row.get("source_url"),
            concept_id=row.get("concept_id"),
            concept_code=metadata.get("concept_code"),
            stage_id=row.get("stage_id"),
            review_status=str(row.get("review_status") or ""),
            license=row.get("license"),
            published_at=row.get("published_at"),
            updated_at=row.get("updated_at"),
            content_hash=metadata.get("content_hash"),
            term=metadata.get("term"),
            term_kr=metadata.get("term_kr"),
            term_en=metadata.get("term_en"),
            publisher=metadata.get("publisher"),
            document_name=metadata.get("document"),
            edition=metadata.get("edition"),
            printed_page=metadata.get("printed_page"),
            related_terms=list(metadata.get("related_terms") or []),
            knowledge_scope=str(metadata.get("knowledge_scope", "scoped")),
            retrieval_method="sparse",
        )
