# 파일 역할: 프로젝트 기능과 데이터 계약을 자동으로 검증하는 테스트 코드입니다.
from app.rag.query.query_rewriter import QueryRewriter


def test_query_rewriter_keeps_message() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    import asyncio

    result = asyncio.run(QueryRewriter().rewrite("hello", []))
    assert result == "hello"
