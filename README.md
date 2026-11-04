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
.venv/bin/python scripts/validate_full_dataset_gold_inputs.py
```

결과는 `reports/pipeline/`, `data/processed/`, `data/labeled/keyword/`에 저장됩니다.
실제 LLM 호출은 위 명령에 포함되어 있지 않으며, 챕터 설정은
`configs/chapters.yaml`에서 관리합니다. 현재 설정은 production curriculum이
없는 상태의 임시 인플레이션 rubric입니다.

원본 파일은 Git에 포함하지 않으므로, 필요한 파일명과 배치 위치는
[`data/README.md`](data/README.md)를 먼저 확인하세요. 원본 데이터가 없으면
파이프라인이 빈 결과를 만들지 않고 입력 누락 오류를 표시합니다.

현재 로컬에 KDI 2,750건과 한국은행 789건이 있으며, 전체 EDA는 두 기관을 함께
읽습니다. `data/`와 저장소 루트에 기관별 미러 파일이 나뉘어 있어도 같은 기관·확장자
파일을 중복 선택하지 않도록 처리합니다. 단, 현재 독립 Gold 라벨은 별도
`라벨링.xlsx` 160건이므로 BOK 문서의 최종 성능 지표는 아직 산출하지 않습니다.

provider 키와 PostgreSQL이 없으면 외부 LLM 호출과 실제 pgvector E2E는 검증할 수 없습니다. 이 경우 단위/계약 테스트와 offline/deterministic 설정을 사용하되, 운영 품질이 검증되었다고 간주하지 않습니다.

### 라벨 품질·메타데이터 감사

`라벨링.xlsx`가 제공되면 다음 명령이 원본을 수정하지 않고 중복 ID, 빈 필드,
평가자 불일치, 골드 비교, 판정 근거, 지정 재검토 용어를 검사합니다.

```bash
.venv/bin/python scripts/validate_label_quality.py
.venv/bin/python scripts/rebuild_precision_pipeline.py
.venv/bin/python scripts/audit_metadata.py
```

`rebuild_precision_pipeline.py`는 로컬의 `라벨링.xlsx`를 기준으로 문자 수·토큰 수,
0/1/2점 분포, 평가자 A/B 일치율, 문제 생성·튜터 검색 정책별 기준선, 기본/확장
키워드의 Precision·Recall·F1을 계산합니다. LLM API 호출은 수행하지 않으며,
현재 골드 라벨은 독립 검증 전의 참고 세트로 표시됩니다.

생성된 행 단위 후보·검수 큐 CSV는 원문을 포함할 수 있으므로 로컬의
`data/labeled/precision/`에만 보관하고 Git에는 추적하지 않습니다. 후보 점수는
관련도 확률이 아닙니다. 요약 결과는 `reports/precision_pipeline_report.md`와
`reports/precision_pipeline_summary.json`에서 확인할 수 있습니다.

멘토·교수님에게 실험 과정을 순서대로 보여줄 때는
[`notebook/precision_eda.ipynb`](notebook/precision_eda.ipynb)를 실행합니다.

### 소규모 LLM 정밀 분류 파일럿

`precision_eda.ipynb`의 LLM 파일럿 셀은 현재 모델의 기존 결과가 있으면 이를
재사용하고, 결과가 없을 때만 KDI/BOK 균형 최대 20건의 소규모 호출을 실행합니다.
매번 새로 호출하려면 Notebook의 `RUN_LLM_API = True`를 사용합니다. 먼저 비용과
입력 토큰을 확인하려면 다음 명령을 실행합니다.

```bash
.venv/bin/python scripts/precision_llm_pilot.py --sample-size 20
```

실제 OpenRouter 호출은 소규모 샘플에 대해서만 명시적으로 `--execute`를 붙여
실행합니다. 결과 원문은 Git에 올리지 않는 `data/labeled/precision/`에 저장됩니다.

```bash
.venv/bin/python scripts/precision_llm_pilot.py --sample-size 20 --execute
```

모델 결과의 `review_status`는 자동 승인하지 않고 항상 `PENDING`으로 저장합니다.
현재 Excel 골드는 독립 평가셋이 아니므로 파일럿 결과만으로 Precision·Recall을
주장하지 않습니다.
Notebook은 기존 파이프라인 모듈을 호출해 같은 결과를 재현하고, 골드 분포와
전략별 Precision·Recall을 표로 확인할 수 있습니다.

Notebook의 전체 데이터셋 셀은 다음과 같은 오프라인 결과를 갱신합니다.

- KDI 2,750건 + BOK 789건 = 고유 문서 3,539건
- 청크 3,545건
- `gpt-4o-mini` 기준 평균 217.75토큰, 총 770,607토큰
- 인플레이션 후보 청크 148건(4.17%)
- 상세 결과: `reports/pipeline/eda_report.md`, `reports/pipeline/dataset_statistics.json`
메타데이터 감사 결과와 제안 스키마는 `reports/taxonomy_audit.md`,
`reports/metadata_schema.json`, `reports/chapter_config.json`에서 확인할 수 있습니다.
평가 지표 산출 전 독립 골드 라벨을 확보해야 하며, 계획은
`reports/evaluation_plan.md`에 정리되어 있습니다.

전체 데이터셋 검증 결과는 `reports/full_dataset_validation_report.md`에서
확인합니다. 검수용 CSV는 원문을 포함하므로 Git에 추적하지 않는 로컬 산출물로
유지합니다.

### 세 가지 분류 방법 비교

Keyword-only, LLM-only, Keyword+LLM Hybrid 비교는 다음 명령으로 실행합니다.
독립 Gold Set이 없으면 외부 API를 호출하거나 성능 수치를 만들지 않고 준비 상태만
기록합니다.

```bash
.venv/bin/python -m scripts.compare_precision_methods
```

KDI 160건과 BOK 160건의 실제 라벨링 Excel을 통합해 원문 대조, A/B 합의 감사,
Keyword 전수 실행 및 기존 LLM 파일럿의 예비 비교를 한 번에 재현하려면 다음
명령을 사용합니다. 기본 실행은 외부 API를 호출하지 않으며 독립 Gold가 없을 때
최종 Precision·Recall·F1을 차단합니다.

```bash
.venv/bin/python scripts/run_kdi_bok_evaluation.py
```

산출물은 `reports/evaluation/`과 `data/processed/evaluation/combined_320.jsonl`에
생성됩니다. 원문 대조·파일 해시·Excel 21열 검증·A/B 불일치는 보고서에 보존되며,
`확정 골드=완료`는 숫자 라벨로 변환하지 않습니다.

통합 결과만 빠르게 다시 확인하려면 실행 결과를 읽는
[`reports/evaluation/evaluation_eda.ipynb`](reports/evaluation/evaluation_eda.ipynb)을
사용합니다. 기존 전체 코퍼스 EDA와 320건 통합 EDA를 함께 보려면
[`notebook/precision_eda.ipynb`](notebook/precision_eda.ipynb)을 실행합니다.
실행 요약과 Notebook 전용 보고서는 각각
`reports/evaluation/precision_eda_summary.json`과
`reports/evaluation/precision_eda_report.md`에 저장됩니다.

독립 검수 큐는 다음 명령으로 생성합니다. 기존 엑셀의 라벨을 복사하지 않고
원문·Document ID·Content Hash를 보존하며 개발셋과 테스트셋을 안정적으로 나눕니다.

```bash
.venv/bin/python -m scripts.prepare_independent_gold_review
```

검수 큐는 `data/labeled/precision/independent_gold_review_queue.csv`에 생성되고,
현재는 `NOT_EVALUATED` 상태로 남습니다. 키워드 미매칭 분석은
`reports/keyword_miss_analysis.md`에서 확인할 수 있으며, 참고 라벨 기반 진단을
최종 테스트셋 튜닝에 사용하지 않습니다.

### 로컬 사람 검수 도구

Streamlit은 현재 의존성에 포함되어 있지 않으므로, 새 패키지를 추가하지 않고
표준 Python CLI 검수 도구를 제공합니다. 기본 입력은 현재 고정된 KDI 160건과
BOK 160건, 총 320건의 독립 검수 큐입니다. 과거 KDI 160건+BOK 205건 템플릿은
레거시 점검용으로만 보존하며 현재 평가와 혼용하지 않습니다. CLI는 제목·원문·출처만 보여주고, 기존 AI 예측과 과거 라벨은 화면에
표시하지 않습니다. 입력한 판정은 원본 템플릿을 수정하지 않고 append-only JSONL로
저장합니다.

```bash
# 전체 미검수 큐를 이어서 검수
.venv/bin/python scripts/gold_review_cli.py --reviewer-id jihoon

# 기관·분할을 제한하여 검수
.venv/bin/python scripts/gold_review_cli.py \
  --reviewer-id jihoon --source BOK --split development

# 같은 평가자의 이전 판정을 새 이벤트로 남기며 수정
.venv/bin/python scripts/gold_review_cli.py \
  --reviewer-id jihoon --include-reviewed

# 두 명 이상의 독립 검수 뒤 최종 합의
.venv/bin/python scripts/gold_review_cli.py \
  --reviewer-id adjudicator --adjudicate

# 이력·원문 근거·데이터 버전·split 누출 검증만 실행
.venv/bin/python scripts/gold_review_cli.py \
  --reviewer-id auditor --validate-only
```

현재 큐와 과거 템플릿의 행 수·기관별 출처·중복 ID는 다음 명령으로 확인합니다.

```bash
.venv/bin/python scripts/reconcile_gold_inputs.py
```

Hybrid 결과에서 키워드 비후보 문서는 명시적인 음성 예측으로 기록되지만,
키워드 후보 중 LLM 결과가 없는 문서는 `NOT_EXECUTED_LLM_MISSING` 상태로 남아
관측 예측에 포함하지 않습니다. 따라서 `279/320`은 완료율이 아니라 현재 관측
가능한 예측 수이며, 미관측 후보 수를 별도로 보고합니다.

검수 이력은 `data/labeled/precision/gold_review_history.jsonl`, 현재 검수 결과
내보내기는 `gold_review_current.csv/jsonl`, 검증 결과는
`reports/gold_review_validation.json`, 평가자 불일치는
`reports/gold_review_disagreements.json`에 저장됩니다. 이 파일들은 원문과 사람의
라벨을 포함할 수 있어 Git 추적에서 제외됩니다. `SINGLE_REVIEWED`는 개인 검수
결과일 뿐이며 최종 Gold가 아닙니다. `ADJUDICATED` 합의가 끝난 행만 기존
비교 파이프라인 입력으로 투영됩니다. 출처 검토, 라이선스 검토, 문제 생성
적합성은 관련도 점수와 별도의 상태로 기록되며, 기본값은 자동 승인되지 않는
`PENDING`입니다.

사람의 합의가 끝난 뒤에는 검수 이력을 기존 템플릿 계약에 연결하여 독립 Gold를
조립합니다. 미완료 행이 하나라도 있으면 `NOT_READY` 상태를 유지합니다.

```bash
.venv/bin/python scripts/assemble_independent_gold.py \
  --history data/labeled/precision/gold_review_history.jsonl
```

독립 검수 완료 CSV가 준비된 뒤에만 최종 비교를 실행합니다. CSV의 필수 상태값은
`gold_set_status=INDEPENDENT_APPROVED`, `review_status=APPROVED`이며, `content_hash`,
`source_group`, `split`, `reviewer_count`, `review_mode`도 필요합니다. 구조는
`configs/independent_gold_schema.json`에서 확인할 수 있습니다.

```bash
.venv/bin/python -m scripts.compare_precision_methods \
  --gold reports/independent_gold_test.csv
```

결과는 `reports/method_comparison_result.json`에 저장하며, 독립 Gold Set이 준비되면
동일 평가셋의 Precision·Recall·F1, FP/FN 오류 파일, 비용·지연시간 집계와 비교
그래프를 함께 생성합니다. 행 단위 CSV와 원문 포함 결과는 Git에 추적하지 않는
`data/labeled/precision/`에 저장합니다. 모든 LLM 결과는 사람 검수 전 `PENDING`입니다.
독립 Gold가 있어도 세 방법 중 하나라도 평가 문서 전체를 예측하지 못하면
`NOT_EVALUATED_INCOMPLETE_PREDICTIONS`로 유지하고 지표·그래프를 생성하지 않습니다.

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
