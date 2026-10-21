# Leren AI Tutor — Multi-turn RAG MVP

FastAPI 기반 경제·금융 학습 튜터입니다. 대화 세션/메시지는 PostgreSQL에 저장하고, 승인된 학습자료는 LlamaIndex와 PostgreSQL pgvector로 chunking·embedding·검색합니다.

## 실행

```bash
cp .env.example .env
# .env의 INTERNAL_API_TOKEN과 필요하면 OPENAI_API_KEY를 설정
python -m pip install -r requirements-dev.txt
python -m uvicorn main:app --reload
python -m pytest -q
```

로컬 PostgreSQL을 쓰면 `DATABASE_URL`의 호스트는 `localhost`, Docker Compose 안에서는 `db`여야 합니다.

```bash
docker compose up --build
```

DB 마이그레이션은 `migrations/001...003`을 순서대로 실행합니다. 프로젝트는 마이그레이션 실행기를 임의로 포함하지 않으므로 PostgreSQL 클라이언트나 운영 마이그레이션 도구로 적용하세요.

## 문서 인덱싱

검증·승인된 `.txt` 또는 `.md` 파일만 `data/`에 넣고 실행합니다. 저장소에는 실제 금융 원천자료를 임의로 추가하지 않았습니다.

```bash
python scripts/ingest_documents.py --path data --source official-material --version 2026-01
```

`OPENAI_API_KEY`가 있으면 설정된 OpenAI 호환 embedding/LLM을 사용하고, 키가 없으면 인덱싱에는 결정적 로컬 embedding, 답변에는 근거 부족을 알리는 오프라인 fallback을 사용합니다. 실제 서비스 품질 검증에는 운영 모델과 승인된 자료가 필요합니다.

## API

`POST /api/tutor/chat`는 `X-Internal-API-Key`와 `X-User-ID` 헤더를 요구합니다. 본문의 `user_id`가 인증된 사용자와 다르면 거부합니다.

```json
{
  "user_id": "user-001",
  "conversation_id": null,
  "message": "GDP가 뭐야?"
}
```

후속 요청에 첫 응답의 `conversation_id`를 전달하면 같은 대화를 이어갑니다. `GET /api/memory/{user_id}`도 같은 서버 간 인증 경계를 사용합니다. Node.js 백엔드가 JWT를 확정하면 `get_current_user_id` 내부를 JWT 검증기로 교체하고 서비스 계층은 그대로 유지할 수 있습니다.
