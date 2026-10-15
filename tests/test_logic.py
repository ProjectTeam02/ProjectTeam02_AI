from app.rag.query.query_rewriter import QueryRewriter


def test_query_rewriter_keeps_message() -> None:
    import asyncio

    result = asyncio.run(QueryRewriter().rewrite("hello", []))
    assert result == "hello"
