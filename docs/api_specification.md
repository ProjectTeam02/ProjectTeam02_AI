# FastAPI API specification

이 문서는 `app/api/v1/routers`와 `app/schemas`의 현재 구현을 요약한 것입니다. 자동 생성 원본은 실행 중인 서버의 `/openapi.json`이며, UI는 `/docs`입니다.

## 공통 실행

```bash
.venv/bin/python -m uvicorn main:app --reload
curl http://localhost:8000/openapi.json
open http://localhost:8000/docs
```

## 엔드포인트

### `GET /health`

인증 없이 서버 상태를 확인합니다.

```json
{"status":"ok"}
```

### `GET /`

루트 진입점의 간단한 실행 확인 응답입니다.

```json
{"status":"success","message":"Leren AI Server is running!"}
```

### `POST /internal/v1/tutor/answer`

Node.js 백엔드 전용 내부 Tutor API입니다. 다음 중 하나로 인증합니다.

- `X-Internal-API-Key: <INTERNAL_API_TOKEN>`
- `Authorization: Bearer <INTERNAL_API_TOKEN>`

`userId`, `conversationId`, `requestId`는 UUID여야 하며, `modelTier`는 `BASIC` 또는 `ADVANCED`입니다. `question`은 `userQuestion`으로도 입력할 수 있습니다. 모든 미지 필드는 거부됩니다.

요청 예시:

```json
{
  "requestId": "aafb8e7b-1e15-428e-8a7d-e746c4aa9c04",
  "conversationId": "60fa8bac-b124-49bc-b8e0-393b611bc34b",
  "userId": "e66e192d-fcae-4575-9c7c-3d2b83f4b5ab",
  "question": "기준금리가 오르면 대출금리는 어떻게 돼?",
  "modelTier": "BASIC",
  "history": [],
  "summary": null,
  "summaryUntilSeq": null,
  "context": {
    "entryPoint": "TUTOR",
    "topicId": "macro",
    "stageId": "stage-1",
    "conceptId": "interest-rate",
    "conceptCode": "ECON_RATE"
  },
  "knowledgeScope": {"conceptCodes": ["ECON_RATE"]}
}
```

응답의 핵심 필드는 다음과 같습니다.

```json
{
  "requestId": "...",
  "answer": "...",
  "rewrittenQuery": "...",
  "groundingStatus": "GROUNDED",
  "historyFromSeq": 1,
  "sources": [
    {
      "documentId": "bok-001",
      "documentVersion": "2026",
      "chunkId": "bok-001:hash:0",
      "titleSnapshot": "기준금리",
      "conceptCode": "ECON_RATE",
      "rank": 1,
      "relevanceScore": 0.91
    }
  ],
  "usage": {
    "modelId": "openai/gpt-4o-mini",
    "embeddingModelId": "openai/text-embedding-3-small",
    "inputTokens": 200,
    "outputTokens": 120,
    "latencyMs": 800,
    "cacheHit": false,
    "retrievalStrategy": "HYBRID_EXACT_VECTOR",
    "estimatedCost": null,
    "currency": null
  }
}
```

FastAPI는 이 경로에서 conversation/message/request를 저장하지 않습니다. Node.js가 요청의 대화 문맥을 제공하고 응답 source/usage를 저장합니다.

### `POST /api/tutor/chat`

기존 호환 API입니다. `X-Internal-API-Key` 또는 Bearer token과 `X-User-ID`가 필요합니다. DTO는 snake_case입니다.

요청:

```json
{
  "user_id": "user-1",
  "message": "기준금리가 뭐야?",
  "conversation_id": null,
  "learning_concept": "interest-rate",
  "incorrect_answer": null
}
```

응답:

```json
{
  "answer": "...",
  "conversation_id": "...",
  "citations": [
    {
      "source_id": "bok-001",
      "document_id": "bok-001",
      "chunk_id": "bok-001:hash:0",
      "title": "기준금리",
      "source": "https://...",
      "url": "https://...",
      "version": "2026",
      "score": 0.9
    }
  ],
  "grounded": true
}
```

### `GET /api/memory/{user_id}`

`X-Internal-API-Key` 또는 Bearer token과 `X-User-ID`가 필요합니다. path의 user ID와 인증 user ID가 다르면 `403`입니다. 응답은 `MemoryResponse` 배열입니다.

```json
[
  {
    "id": "...",
    "user_id": "user-1",
    "content": "금리 개념을 복습 중",
    "source": "tutor",
    "created_at": "2026-10-29T00:00:00Z"
  }
]
```

## 오류 처리

| 상태 | 조건 |
|---:|---|
| 401 | 내부 토큰 누락/불일치, `X-User-ID` 누락 |
| 403 | 다른 사용자의 대화/메모리 접근 |
| 404 | 대화가 존재하지 않음 |
| 422 | Pydantic 입력 검증 실패, 잘못된 UUID/sequence/필드 |
| 503 | provider 설정, retrieval, generation 실패 |
| 504 | 내부 Tutor 요청의 설정된 timeout 초과 |

오류 응답은 FastAPI 기본 `{"detail": "..."}` 형식입니다. 내부 경로는 key나 provider secret을 오류 메시지에 노출하지 않습니다.

## 인증 및 환경변수

`app/core/config.py`가 `.env`와 process environment를 읽습니다. 실제 키는 코드에 하드코딩하지 않습니다.

```dotenv
INTERNAL_API_TOKEN=change-me
OPENROUTER_API_KEY=sk-or-v1-...
LLM_PROVIDER=openrouter
EMBEDDING_PROVIDER=openrouter
```

## 확인 범위

OpenAPI schema 생성, route 등록, Pydantic 계약, 인증 실패 응답은 테스트할 수 있습니다. 실제 LLM 응답, embedding 품질, pgvector network path는 API key와 PostgreSQL 실행 상태가 없으면 검증할 수 없습니다.
