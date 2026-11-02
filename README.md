# Leren AI Tutor

Leren AI는 경제·금융 학습자료를 근거로 답변하는 FastAPI 기반 Multi-turn RAG 서버입니다. LlamaIndex와 PostgreSQL/pgvector를 사용하며, Node.js 백엔드가 내부 Tutor API를 호출하는 구조를 지원합니다.

현재 구현 범위는 다음과 같습니다.

- 승인(`approved`) 문서만 인덱싱·검색하는 RAG
- 대화 이력/요약을 제한된 크기로 반영하는 Multi-turn 질문 재작성
- LlamaIndex PGVectorStore 기반 임베딩 검색과 한국은행 용어 exact/hybrid 검색
- 검색 근거의 문서 ID·청크 ID·간단한 내용 중첩을 확인하는 citation/grounding 검증
- OpenRouter 또는 OpenAI 호환 LLM·embedding provider
- 근거와 기존 question blueprint를 검증해 `DRAFT_READY` 계획을 만드는 문제 생성 준비 로직

문제 게시 승인, 사용자 채점, 보상/HP/stage 완료, 대화·메시지·요청 저장은 현재 Node.js 백엔드 책임으로 분리되어 있습니다. AWS S3는 현재 Python 코드, 의존성, 환경변수에서 사용 흔적을 확인하지 못했습니다.

## 기술 스택

- Python 3.12, FastAPI, Pydantic Settings
- LlamaIndex 0.14 계열
- PostgreSQL 16 + pgvector, SQLAlchemy async, asyncpg/psycopg
- OpenRouter 또는 OpenAI 호환 LLM/embedding
- Docker Compose: AI 서버 + pgvector PostgreSQL

## 실행

Python 3.12 가상환경을 만들고 개발 의존성을 설치합니다.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements-dev.txt
```

`.env`에는 최소한 provider 설정을 넣습니다. 실제 키는 커밋하지 않습니다.

```dotenv
OPENROUTER_API_KEY=sk-or-v1-...
LLM_PROVIDER=openrouter
EMBEDDING_PROVIDER=openrouter
INTERNAL_API_TOKEN=change-me
```

Docker로 PostgreSQL을 실행할 때 호스트 포트는 `5433`입니다. 운영 대화 테이블은 Node.js가 소유하므로 migration 적용 순서와 소유권은 [migrations/README.md](migrations/README.md) 및 [AI Backend ERD mapping](docs/AI_BACKEND_ERD_MAPPING.md)을 확인하세요.

```bash
docker compose up -d db
for migration in migrations/*.sql; do
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d leren < "$migration"
done
.venv/bin/python -m uvicorn main:app --reload
```

또는 AI 서버까지 Compose로 실행합니다.

```bash
docker compose up --build
```

## 주요 API

| Method | Path | 용도 |
|---|---|---|
| GET | `/health` | 상태 확인 |
| GET | `/` | 루트 실행 확인 |
| POST | `/internal/v1/tutor/answer` | Node.js 전용 Tutor API, 내부 토큰 필요 |
| POST | `/api/tutor/chat` | 기존 snake_case 공개 호환 API |
| GET | `/api/memory/{user_id}` | 인증 사용자의 메모리 조회 |
| GET | `/docs` | Swagger UI |

내부 API의 상세 계약은 [docs/api_specification.md](docs/api_specification.md)와 [docs/TUTOR_INTERNAL_API_CONTRACT.md](docs/TUTOR_INTERNAL_API_CONTRACT.md)에 있습니다.

## 문서 인덱싱

네트워크 수집은 자동으로 수행하지 않습니다. 검토된 로컬 manifest 또는 한국은행 데이터셋을 준비한 뒤 실행합니다.

```bash
.venv/bin/python -m scripts.ingest_documents --manifest data/manifest.json
.venv/bin/python -m scripts.ingest_documents \
  --bok-source data/한국은행/bok_terms_2026.json \
  --bok-terms data/한국은행/bok_terms_2026_rag.jsonl
```

본문 hash, 승인 상태, embedding provider/model/dimension을 확인하며 기존 데이터나 사용자 데이터를 삭제하지 않습니다. 자세한 처리 순서는 [docs/rag_pipeline.md](docs/rag_pipeline.md)를 참고하세요.

## 테스트와 정적 검사

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

## 데이터셋 EDA 및 선별 파이프라인

현재 `data/`의 KDI/BOK JSON·JSONL mirror를 중복 집계하지 않고, 원문을 수정하지
않은 채 EDA·정규화·청크·키워드 후보·LLM 비용 dry-run을 실행합니다.

```bash
.venv/bin/python -m scripts.run_eda
.venv/bin/python -m scripts.make_chunks
.venv/bin/python -m scripts.keyword_filter
.venv/bin/python -m scripts.estimate_classification_cost
```

결과는 `reports/pipeline/`, `data/processed/`, `data/labeled/keyword/`에 저장됩니다.
실제 LLM 호출은 위 명령에 포함되어 있지 않으며, 챕터 설정은
`configs/chapters.yaml`에서 관리합니다. 현재 설정은 production curriculum이
없는 상태의 임시 인플레이션 rubric입니다.

원본 파일은 Git에 포함하지 않으므로, 필요한 파일명과 배치 위치는
[`data/README.md`](data/README.md)를 먼저 확인하세요. 원본 데이터가 없으면
파이프라인이 빈 결과를 만들지 않고 입력 누락 오류를 표시합니다.

provider 키와 PostgreSQL이 없으면 외부 LLM 호출과 실제 pgvector E2E는 검증할 수 없습니다. 이 경우 단위/계약 테스트와 offline/deterministic 설정을 사용하되, 운영 품질이 검증되었다고 간주하지 않습니다.

### 라벨 품질·메타데이터 감사

`라벨링.xlsx`가 제공되면 다음 명령이 원본을 수정하지 않고 중복 ID, 빈 필드,
평가자 불일치, 골드 비교, 판정 근거, 지정 재검토 용어를 검사합니다.

```bash
.venv/bin/python scripts/validate_label_quality.py
.venv/bin/python scripts/audit_metadata.py
```

현재 저장소에는 `라벨링.xlsx`가 없어 라벨 검사는 `NOT_AVAILABLE`로 기록됩니다.
요청문에 제시된 160건 수치는 검증되지 않은 참고값으로만 보관합니다. 처리된 청크
아티팩트가 있는 경우 키워드 후보는 `reports/keyword_candidates.csv`와
`data/labeled/keyword/`에 저장되며, 후보 점수는 관련도 확률이 아닙니다.
메타데이터 감사 결과와 제안 스키마는 `reports/taxonomy_audit.md`,
`reports/metadata_schema.json`, `reports/chapter_config.json`에서 확인할 수 있습니다.
평가 지표 산출 전 독립 골드 라벨을 확보해야 하며, 계획은
`reports/evaluation_plan.md`에 정리되어 있습니다.

## 프로젝트 구조

```text
app/
├── main.py                         FastAPI 앱 조립
├── api/v1/routers/                 health, tutor, memory 라우터
├── core/                           설정·예외·로깅
├── schemas/                        Pydantic 요청/응답 모델
├── services/                       Tutor/Memory 유스케이스
├── repositories/                   PostgreSQL 데이터 접근
├── db/                             연결·SQLAlchemy 모델
├── rag/
│   ├── ingestion/                  문서/BOK 데이터 로딩
│   ├── indexing/                   LlamaIndex·embedding·pgvector 인덱싱
│   ├── retrieval/                  검색 정책·query rewrite·LlamaIndex adapter
│   ├── memory/                     대화 이력과 bounded context
│   ├── generation/                 근거 기반 답변 생성
│   ├── grounding/                  citation/grounding 검증
│   └── pipeline.py                 Multi-turn RAG orchestration
└── question_generation/            데이터셋 검증·근거 기반 초안 계획
```

이동 전후 구조와 파일별 책임은 [docs/directory_structure.md](docs/directory_structure.md), 요청 흐름은 [docs/architecture.md](docs/architecture.md), 시각화는 [docs/project_structure.html](docs/project_structure.html)에서 확인할 수 있습니다. 과거 import 경로는 기존 테스트·스크립트 호환을 위해 얇은 shim으로 남겨 두었습니다.
