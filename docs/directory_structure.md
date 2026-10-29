# Leren AI 디렉터리 구조

이 문서는 2026-10-29 현재 저장소의 Python 애플리케이션 구조를 기준으로 작성했습니다. `.venv`, `__pycache__`, `.pytest_cache`, `.ruff_cache`, PyCharm `.idea`와 Git 메타데이터는 제품 소스 트리에서 제외했습니다.

## 현재 구조

```text
ProjectTeam02_AI/
├── app/
│   ├── main.py
│   ├── api/
│   │   ├── dependencies.py
│   │   └── v1/routers/
│   │       ├── health.py
│   │       ├── memory.py
│   │       └── tutor.py
│   ├── core/
│   │   ├── config.py
│   │   ├── exceptions.py
│   │   └── logging.py
│   ├── schemas/
│   │   ├── memory.py
│   │   └── tutor.py
│   ├── services/
│   │   ├── memory_service.py
│   │   └── tutor_service.py
│   ├── repositories/
│   │   ├── conversation_repository.py
│   │   ├── memory_repository.py
│   │   └── rag_repository.py
│   ├── db/
│   │   ├── connection.py
│   │   └── models.py
│   ├── rag/
│   │   ├── ingestion/
│   │   │   ├── bok_terms_loader.py
│   │   │   └── document_loader.py
│   │   ├── indexing/
│   │   │   ├── embedding_model.py
│   │   │   ├── index_manager.py
│   │   │   ├── indexer.py
│   │   │   ├── llm_factory.py
│   │   │   └── vector_store.py
│   │   ├── retrieval/
│   │   │   ├── llamaindex_retriever.py
│   │   │   ├── query_rewriter.py
│   │   │   ├── retriever.py
│   │   │   └── types.py
│   │   ├── memory/
│   │   │   ├── context_builder.py
│   │   │   └── history_manager.py
│   │   ├── generation/answer_generator.py
│   │   ├── grounding/citation_validator.py
│   │   └── pipeline.py
│   ├── question_generation/
│   │   ├── dataset.py
│   │   └── generator.py
│   └── evaluation/
│       ├── rag_metrics.py
│       └── relevance.py
├── data/                           BOK 데이터·평가 입력
├── scripts/                        인덱싱·검증·평가 CLI
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   ├── test_internal_tutor_api.py
│   ├── test_multiturn_mvp.py
│   ├── test_p0_contracts.py
│   ├── test_openrouter_config.py
│   ├── test_bok_knowledge_base.py
│   ├── test_question_generation.py
│   ├── test_mentor_dataset.py
│   ├── test_logic.py
│   └── test_project_structure.py
├── docs/                           설계·운영·평가 문서
├── migrations/                     PostgreSQL DDL 및 소유권 문서
├── notebook/                       탐색·평가용 Jupyter notebook
├── integration/                    통합 산출물 자리
├── outputs/                        평가 결과
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── main.py                         루트 호환 실행 진입점
└── README.md
```

`scripts/`에는 `ingest_documents.py`, `evaluate_bok_rag.py`, `check_knowledge_dataset.py`, `check_curriculum.py`, `select_concept_documents.py`가 있습니다. `data/`에는 BOK source/RAG JSON·JSONL과 평가 질문이 있고, `docs/`에는 기존 ERD·계약·dataset 문서와 이 구조 문서가 함께 있습니다.

## 계층별 역할과 연결

| 영역 | 담당 기능 | 대표 파일 | 연결 |
|---|---|---|---|
| `api/v1/routers` | HTTP 경로, DTO, 오류 매핑 | `tutor.py` | `dependencies` → `services` |
| `core` | 환경변수, 예외, 로깅 | `config.py` | 모든 계층의 공통 기반 |
| `schemas` | Pydantic 요청/응답 검증 | `tutor.py` | Router ↔ Service 계약 |
| `services` | 유스케이스와 권한/사용량 처리 | `tutor_service.py` | RAG pipeline, repositories |
| `repositories` | SQLAlchemy 데이터 접근 | `rag_repository.py` | `db.connection`, `db.models` |
| `db` | DB 엔진과 모델 | `connection.py`, `models.py` | PostgreSQL/pgvector |
| `rag/ingestion` | 로컬 문서/BOK JSONL 정제·변환 | `document_loader.py` | `rag/indexing` |
| `rag/indexing` | SentenceSplitter, embedding, PGVectorStore | `indexer.py`, `index_manager.py` | PostgreSQL + LlamaIndex |
| `rag/retrieval` | query rewrite, exact/vector/hybrid 검색 | `retriever.py` | indexing adapter, memory |
| `rag/memory` | 대화 이력·요약의 bounded context | `history_manager.py` | pipeline, Node.js payload |
| `rag/generation` | LLM 호출 및 offline 답변 | `answer_generator.py` | context + provider |
| `rag/grounding` | citation identity/overlap 검증 | `citation_validator.py` | 검색 결과 + 생성 답변 |
| `rag/pipeline.py` | 전체 Multi-turn RAG 순서 제어 | `MultiTurnRAG` | memory → rewrite → retrieve → generate |
| `question_generation` | 커리큘럼/멘토 데이터 검증, 초안 계획 | `dataset.py`, `generator.py` | 승인 근거 + blueprint |
| `evaluation` | 검색·관련성 평가 | `rag_metrics.py` | scripts/notebooks |

## 실제 의존 방향

```text
Router
  → Service
    → RAG pipeline
      → Memory / Retrieval / Generation / Grounding
        → LlamaIndex indexing adapter
          → PostgreSQL + pgvector

Router → Schema
Service → Repository → DB model/connection
Scripts → ingestion + indexing + repository
```

라우터에는 LLM·검색 구현을 두지 않았고, DB repository는 HTTP 객체를 알지 않습니다. `app/api/dependencies.py`는 설정을 읽어 provider, history manager, retriever, generator, validator를 조립하는 composition root 역할을 합니다.

현재 별도 `rag/prompts` 디렉터리는 없습니다. Tutor와 query-rewrite prompt는 각각 `AnswerGenerator`와 `QueryRewriter` 내부에 있으며, 실제 템플릿이 늘어나기 전까지 빈 prompt 파일을 만들지 않았습니다.

이동 전 경로를 사용하는 호환 shim도 남아 있습니다: `app/api/routes`, `app/db/postgres.py`, `app/db/repositories`, `app/ingestion`, `app/rag/llamaindex`, `app/rag/query`, `app/rag/pipelines`, `app/services/question_generation.py`. 이 파일들은 새 구현을 re-export할 뿐이며 신규 참조 대상이 아닙니다.

## 이전 구조에서의 이동

| 변경 전 | 변경 후 | 이유 |
|---|---|---|
| `app/api/routes/*` | `app/api/v1/routers/*` | API 버전과 라우터 역할을 분리 |
| `app/db/repositories/*` | `app/repositories/*` | 데이터 접근 계층을 DB 연결/모델과 분리 |
| `app/db/postgres.py` | `app/db/connection.py` | 연결 책임을 이름으로 명확화 |
| `app/ingestion/document_loader.py` | `app/rag/ingestion/document_loader.py` | RAG 입력 파이프라인 소속 명시 |
| `app/rag/llamaindex/*` | `app/rag/indexing/*` | LlamaIndex가 retrieval adapter와 indexing을 모두 포함하던 구조 해소 |
| `app/rag/llamaindex/retriever.py` | `app/rag/retrieval/llamaindex_retriever.py` | 검색 adapter를 retrieval 계층으로 이동 |
| `app/rag/query/query_rewriter.py` | `app/rag/retrieval/query_rewriter.py` | query rewriting을 검색 흐름과 함께 배치 |
| `app/rag/pipelines/multiturn_rag.py` | `app/rag/pipeline.py` | 단일 orchestration 진입점을 짧고 명확하게 표시 |
| `app/services/question_generation.py` | `app/question_generation/generator.py` | 서비스 API와 생성 도메인 로직 분리 |
| `app/ingestion/mentor_dataset.py` | `app/question_generation/dataset.py` | 커리큘럼·question blueprint 검증 책임에 맞춤 |

## 호환 shim

기존 테스트나 외부 스크립트가 사용하던 이전 import 경로는 즉시 제거하지 않았습니다. 예를 들어 `app.rag.llamaindex.indexer`는 `app.rag.indexing.indexer`를 재-export합니다. shim은 새 로직을 중복 구현하지 않으며, 신규 코드는 새 경로를 사용합니다.
