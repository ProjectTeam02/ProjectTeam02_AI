from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from app.ingestion.bok_terms_loader import (
    BOKTermCatalog,
    load_bok_terms,
    validate_bok_dataset,
)
from app.rag.memory.history_manager import HistoryManager
from app.rag.pipelines.multiturn_rag import MultiTurnRAG
from app.rag.query.query_rewriter import QueryRewriter
from app.rag.retrieval.retriever import Retriever
from app.rag.retrieval.types import RetrievedDocument


@pytest.fixture
def bok_dataset(tmp_path: Path) -> tuple[Path, Path]:
    def row(
        document_id: str,
        term: str,
        *,
        review_flags: list[str] | None = None,
        review_status: str = "approved",
    ) -> dict:
        definition = f"{term}의 검증용 정의"
        content = f"용어: {term}\n정의: {definition}"
        return {
            "id": document_id,
            "document_id": document_id,
            "source_id": "BOK-EFT-800-2026",
            "document_version": "2026",
            "title": term,
            "term": term,
            "term_kr": term,
            "term_en": None,
            "definition": definition,
            "content": content,
            "publisher": "한국은행",
            "document": "경제금융용어 800선",
            "edition": "2026",
            "printed_page": 76,
            "related_terms": ["환매조건부매매/RP/Repo"] if term == "기준금리" else [],
            "review_flags": review_flags or [],
            "review_status": review_status,
            "source_url": "https://www.bok.or.kr/source",
            "license": "permission-and-attribution-review-required",
            "content_hash": hashlib.sha256(content.encode("utf-8")).hexdigest(),
        }

    rows = [
        row("bok-test-001", "기준금리"),
        row(
            "bok-test-002",
            "검토용어",
            review_flags=["formula_or_layout_review"],
            review_status="needs_review",
        ),
    ]
    source = tmp_path / "bok_terms_2026.json"
    rag = tmp_path / "bok_terms_2026_rag.jsonl"
    source.write_text(
        json.dumps({"records": rows}, ensure_ascii=False), encoding="utf-8"
    )
    rag.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in rows) + "\n",
        encoding="utf-8",
    )
    return source, rag


def bok_document(
    term: str,
    document_id: str,
    related_terms: list[str] | None = None,
    method: str = "vector",
) -> RetrievedDocument:
    return RetrievedDocument(
        content=f"{term}에 대한 한국은행 정의",
        source="https://www.bok.or.kr/source",
        source_id="BOK-EFT-800-2026",
        document_id=document_id,
        chunk_id=f"{document_id}:chunk-0",
        title=term,
        term=term,
        publisher="한국은행",
        edition="2026",
        printed_page=76,
        related_terms=related_terms or [],
        review_status="approved",
        retrieval_method=method,
    )


def test_bok_source_and_rag_dataset_are_consistent(bok_dataset):
    source, rag = bok_dataset
    validation = validate_bok_dataset(source, rag)
    assert validation.source_count == 2
    assert validation.rag_count == 2
    assert validation.review_count == 1
    assert validation.approved_count == 1
    assert validation.duplicate_ids == ()
    assert validation.missing_in_rag == ()
    assert validation.missing_in_source == ()


def test_bok_loader_preserves_metadata_and_excludes_review_records(bok_dataset):
    source, rag = bok_dataset
    documents = load_bok_terms(rag, source)
    assert len(documents) == 1
    assert all(document.review_status == "approved" for document in documents)
    base_rate = next(document for document in documents if document.term == "기준금리")
    assert base_rate.document_id == "bok-test-001"
    assert base_rate.source_id == "BOK-EFT-800-2026"
    assert base_rate.publisher == "한국은행"
    assert base_rate.edition == "2026"
    assert base_rate.printed_page == 76
    assert base_rate.knowledge_scope == "global"
    assert base_rate.related_terms == ["환매조건부매매/RP/Repo"]


def test_bok_exact_term_catalog_prefers_longest_approved_term(bok_dataset):
    _, rag = bok_dataset
    catalog = BOKTermCatalog(rag)
    assert catalog.match("기준금리가 오르면 대출금리는 어떻게 돼?")[0] == "기준금리"
    assert catalog.match("화성의 날씨를 알려줘") == []


@pytest.mark.asyncio
async def test_hybrid_policy_ranks_exact_match_and_expands_related_terms(bok_dataset):
    _, rag = bok_dataset
    base_rate = bok_document(
        "기준금리", "bok800-154", ["환매조건부매매/RP/Repo"], "exact"
    )
    repo = bok_document("환매조건부매매/RP/Repo", "bok800-736", method="exact")
    semantic = bok_document("금리자유화", "bok800-116")

    class Backend:
        async def retrieve(self, query, top_k, concept_id=None, stage_id=None):
            return [semantic]

        async def retrieve_exact(self, terms, top_k, concept_id=None, stage_id=None):
            mapping = {base_rate.term: base_rate, repo.term: repo}
            return [mapping[term] for term in terms if term in mapping][:top_k]

    retriever = Retriever(
        Backend(),
        top_k=5,
        exact_matcher=BOKTermCatalog(rag),
        related_term_top_k=2,
    )
    first = await retriever.retrieve("기준금리가 뭐야?")
    expanded = await retriever.retrieve_related(first)
    assert [document.document_id for document in first][:2] == [
        "bok800-154",
        "bok800-116",
    ]
    assert "bok800-736" in [document.document_id for document in expanded]


@pytest.mark.asyncio
async def test_three_turn_rewrite_keeps_original_base_rate_topic():
    rewriter = QueryRewriter()
    history = HistoryManager()
    conversation = await history.create("user-1")
    await history.append_turn(
        conversation.conversation_id,
        "user-1",
        "기준금리가 뭐야?",
        "기준금리는 중앙은행의 정책금리야.",
    )
    await history.append_turn(
        conversation.conversation_id,
        "user-1",
        "그럼 그게 오르면 어떤 일이 생겨?",
        "대출금리 상승 압력이 생길 수 있어.",
    )
    loaded = await history.load(conversation.conversation_id, "user-1")
    rewritten = await rewriter.rewrite("대출금리랑 무슨 관계가 있어?", loaded)
    assert "기준금리" in rewritten
    assert "대출금리" in rewritten


def test_pipeline_contract_still_exposes_retriever_related_expansion():
    pipeline = MultiTurnRAG()
    assert hasattr(pipeline.retriever, "retrieve_related")
