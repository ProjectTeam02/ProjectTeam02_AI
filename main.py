# 파일 역할: 프로젝트 실행 진입점과 FastAPI 애플리케이션 실행을 담당합니다.
from app.main import app

__all__ = ["app"]


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
