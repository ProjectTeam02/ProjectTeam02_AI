# Leren AI Tutor — Multi-turn RAG MVP

FastAPI, LlamaIndex, PostgreSQL/pgvector 기반 경제·금융 튜터입니다. 같은
`conversationId`의 최근 대화를 사용해 후속 질문을 검색용 독립 질문으로 바꾸고,
`approved` 문서만 검색하여 답변·실제 citation·보수적인 `grounded` 값을 반환합니다.

## 빠른 시작

Python 3.12가 필요합니다. 현재 프로젝트의 가상환경이 다른 버전이면 재사용하지 말고
PyCharm에서 Python 3.12 인터프리터로 새 `.venv`를 만드세요.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -U pip
.venv/bin/python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Docker Compose의 PostgreSQL은 호스트 `localhost:5433`에 노출됩니다. AI 컨테이너
안에서는 compose가 `db:5432`를 주입합니다.

```bash
docker compose up -d db
for migration in migrations/*.sql; do
  docker compose exec -T db psql -v ON_ERROR_STOP=1 -U postgres -d leren < "$migration"
done
docker compose up -d ai
```

호스트/PyCharm 실행:

```bash
.venv/bin/python -m uvicorn main:app --reload
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

`OPENAI_API_KEY`가 없어도 import, `/health`, mock 테스트는 동작합니다. API 없이
로컬 pgvector E2E를 명시적으로 시험하려면 `.env`에
`EMBEDDING_PROVIDER=deterministic`, `LLM_PROVIDER=offline`을 설정합니다. 이 모드는
품질 평가나 운영용이 아닙니다. `EMBEDDING_PROVIDER=openai`인데 키가 없으면
인덱싱/검색은 성공으로 위장하지 않고 503/설정 오류를 반환합니다.

## 승인 문서 인덱싱

네트워크 수집은 자동 실행하지 않습니다. 자료의 접근 권한·라이선스·갱신 주기와
내용 검수를 먼저 완료한 뒤 로컬 manifest를 사용합니다.

```bash
.venv/bin/python -m scripts.ingest_documents --manifest data/manifest.json
```

manifest 형식은 [docs/source-manifest.example.json](docs/source-manifest.example.json)을
참고하세요. `review_status`가 설정의 `APPROVED_REVIEW_STATUS`와 다르면 전체 실행이
실패합니다. 같은 본문은 SHA-256 `content_hash`로 중복 적재하지 않으며, 문서가
바뀌면 새 청크를 저장하고 이전 vector node를 제거합니다. 컬렉션에 기록된 embedding
provider/model/dimension이 현재 설정과 다르면 명시적으로 재인덱싱을 요구합니다.

### 한국은행 2026 경제금융용어 KB

```bash
.venv/bin/python -m scripts.ingest_documents \
  --bok-source data/bok_terms_2026.json \
  --bok-terms data/bok_terms_2026_rag.jsonl
```

789개 용어 중 수식·레이아웃 재검토가 필요한 29개는 `needs_review`로
유지하고 자동 인덱싱하지 않습니다. 데이터 구조, 검색 정책, 검증 결과와
라이선스 확인 사항은 [BOK Knowledge Base 문서](docs/BOK_KNOWLEDGE_BASE.md)를
참고하세요.

## 내부 Tutor API

Node.js만 `POST /internal/v1/tutor/answer`를 호출합니다. `X-Internal-API-Key` 또는
Bearer token은 `.env`의 `INTERNAL_API_TOKEN`과 일치해야 합니다.

```bash
curl -X POST http://localhost:8000/internal/v1/tutor/answer \
  -H 'Content-Type: application/json' \
  -H 'X-Internal-API-Key: change-me' \
  -d '{
    "userId":"test-user-001",
    "conversationId":null,
    "requestId":"request-001",
    "stageId":"stage-001",
    "conceptId":"concept-001",
    "question":"기준금리가 오르면 어떤 영향이 있나요?"
  }'
```

응답의 `conversationId`를 후속 요청에 그대로 넣습니다. `requestId` 재전송은 같은
저장 답변을 반환하고 메시지를 중복 저장하지 않습니다. `/api/tutor/chat`는 기존
테스트 호환 경로이며 운영 앱은 Node.js 공개 API만 호출해야 합니다.

상세한 데이터 흐름, migration, API 응답, 검증 범위와 협의 항목은
[P0 구현 문서](docs/P0_IMPLEMENTATION.md)에 있습니다.
