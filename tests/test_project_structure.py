# 파일 역할: 프로젝트 기능과 데이터 계약을 자동으로 검증하는 테스트 코드입니다.
from pathlib import Path

PROJECT_ROOT = Path(__file__).parents[1]


def test_required_directories_exist() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    for name in (
        "app",
        "scripts",
        "notebook",
        "data",
        "integration",
        "docs",
    ):
        assert (PROJECT_ROOT / name).is_dir()
