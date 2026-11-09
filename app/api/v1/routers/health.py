# 파일 역할: HTTP API 계층의 의존성 또는 라우터를 정의합니다.
from fastapi import APIRouter

router = APIRouter(tags=["health"])


@router.get("/health")
async def health() -> dict[str, str]:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    return {"status": "ok"}
