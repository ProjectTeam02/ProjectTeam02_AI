# 파일 역할: 환경 설정, 예외, 로깅 등 애플리케이션 공통 기능을 제공합니다.
import logging


def configure_logging() -> None:
    # 함수 역할: 입력을 처리하고 필요한 결과를 반환합니다.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
