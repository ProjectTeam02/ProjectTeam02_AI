# 파일 역할: 프로젝트 기능과 데이터 계약을 자동으로 검증하는 테스트 코드입니다.
from fastapi.testclient import TestClient

from app.main import app


def test_health() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    client = TestClient(app)
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
