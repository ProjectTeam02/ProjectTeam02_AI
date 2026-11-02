# 프로젝트 코드 주석 및 파일 역할 가이드

이 문서는 멘토님과 교수님이 저장소를 처음 열었을 때 각 파일의 책임과 실행 흐름을 빠르게 파악할 수 있도록 작성한 안내서입니다.

## 주석 작성 원칙

- Python 파일의 첫 줄에는 파일의 책임 범위를 설명하는 `파일 역할` 주석을 둡니다.
- 함수와 클래스에 이미 docstring이 있으면 해당 설명을 우선 사용합니다.
- 복잡한 처리에는 구현 방법보다 **왜 필요한지**, **어떤 입력을 받는지**, **어떤 결과를 보장하는지**를 설명합니다.
- 키워드 필터는 최종 승인 판정이 아니라 넓은 후보 추출 단계라는 점을 유지합니다.
- 외부 LLM 호출, DB 쓰기, 원본 데이터 변경 여부는 실행 스크립트와 Notebook에서 명확히 표시합니다.
- 테스트 코드는 테스트 대상과 실패 시 보장하려는 계약을 설명합니다.

## 디렉터리별 책임

| 경로 | 책임 |
| --- | --- |
| `app/api` | FastAPI 라우터와 인증·서비스 의존성 |
| `app/core` | 환경 설정, 예외, 로깅 |
| `app/dataset_pipeline` | 정규화, 토큰 계산, 청크, 키워드 후보, LLM 분류 스키마 |
| `app/db` | SQLAlchemy 모델과 PostgreSQL 연결 |
| `app/rag` | 검색, 질의 재작성, 인덱싱, 답변 생성, 대화 메모리 |
| `app/services` | API 요청과 RAG·저장소 사이의 업무 흐름 |
| `app/schemas` | API 입력·출력 계약과 검증 |
| `scripts` | 독립 실행 가능한 EDA·검증·생성 작업 |
| `tests` | API, 데이터 계약, RAG, 파이프라인 자동 검증 |
| `notebook` | 설명 중심의 실험 및 결과 확인 |
| `configs` | 코드와 분리한 챕터·EDA 실행 설정 |

## 주석을 넣을 수 없는 파일

JSON과 JSONL은 표준 문법상 주석을 허용하지 않습니다. 따라서 다음 파일은 원본 구조를 깨지 않도록 수정하지 않고, 해당 파일의 목적과 해석 방법을 이 문서와 인접한 Markdown 보고서에서 설명합니다.

- `data/**/*.json`, `data/**/*.jsonl`
- `reports/**/*.json`
- `outputs/**/*.json`
- `package-lock.json`

YAML, TOML, Docker Compose 설정에는 문법이 허용하는 `#` 주석을 추가했습니다.

## 읽는 순서

1. `README.md`에서 실행 명령과 전체 구조를 확인합니다.
2. `docs/architecture.md`와 `docs/rag_pipeline.md`에서 서비스 구조를 확인합니다.
3. `notebook/rag_evaluation.ipynb`에서 검색 평가와 데이터 선별 실험을 확인합니다.
4. `app/dataset_pipeline`과 `scripts`에서 실제 재사용 가능한 처리 코드를 확인합니다.
5. `tests`에서 각 기능의 검증 조건을 확인합니다.
