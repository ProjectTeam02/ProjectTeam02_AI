# Internal Tutor API Contract

## Endpoint and authentication

`POST /internal/v1/tutor/answer`

React Native나 일반 외부 클라이언트가 직접 호출하지 않는다. Node.js Backend가
`X-Internal-API-Key: ${INTERNAL_API_TOKEN}` 또는 `Authorization: Bearer
${INTERNAL_API_TOKEN}` 헤더를 사용한다. 토큰이 비어 있거나 일치하지 않으면 `401`이다.
`INTERNAL_API_TOKEN`은 운영 환경에서 반드시 주입한다.

## Request

`requestId`, `conversationId`, `userId`는 UUID 문자열이다. 학습 문맥 ID는 백엔드의
기존 식별자 형식을 보존하는 문자열이다. `conversationId`는 새 대화라도 Node.js가
먼저 생성해서 전달해야 한다. FastAPI는 ID를 생성하지 않는다.

```json
{
  "requestId": "aafb8e7b-1e15-428e-8a7d-e746c4aa9c04",
  "conversationId": "60fa8bac-b124-49bc-b8e0-393b611bc34b",
  "userId": "e66e192d-fcae-4575-9c7c-3d2b83f4b5ab",
  "question": "그럼 그게 오르면 대출금리는 어떻게 돼?",
  "modelTier": "BASIC",
  "history": [
    {"sequenceNo": 1, "role": "USER", "content": "기준금리가 뭐야?"},
    {"sequenceNo": 2, "role": "ASSISTANT", "content": "중앙은행의 정책금리야."}
  ],
  "summary": null,
  "summaryUntilSeq": null,
  "context": {
    "entryPoint": "CONCEPT",
    "topicId": null,
    "stageId": null,
    "conceptId": null,
    "conceptCode": null,
    "questionId": null,
    "attemptId": null
  },
  "knowledgeScope": {"conceptCodes": []}
}
```

`history`는 sequence가 오름차순이어야 하며 최대 50개다. `summary`를 보내면
`summaryUntilSeq`도 함께 보내야 한다. 요약 이전의 메시지는 중복 컨텍스트로 보내지
않고, 토큰 예산 내에서 최근 메시지만 사용한다.

## Response (`200`)

```json
{
  "requestId": "aafb8e7b-1e15-428e-8a7d-e746c4aa9c04",
  "answer": "기준금리가 오르면 ...",
  "rewrittenQuery": "기준금리가 상승할 때 대출금리에 미치는 영향",
  "groundingStatus": "GROUNDED",
  "historyFromSeq": 1,
  "sources": [
    {
      "documentId": "bok800-154",
      "documentVersion": "2026",
      "chunkId": "bok800-154:abc123:0",
      "titleSnapshot": "기준금리",
      "conceptCode": null,
      "rank": 1,
      "relevanceScore": 1.0
    }
  ],
  "usage": {
    "modelId": "gpt-4o-mini",
    "embeddingModelId": "text-embedding-3-small",
    "inputTokens": 320,
    "outputTokens": 84,
    "latencyMs": 620,
    "cacheHit": false,
    "retrievalStrategy": "HYBRID_EXACT_VECTOR",
    "estimatedCost": null,
    "currency": null
  }
}
```

`groundingStatus`는 `GROUNDED` 또는 `INSUFFICIENT`다. `relevanceScore`는 검색
어댑터가 0~1 유사도 점수로 제공한 경우만 반환하며, 거리값이나 범위를 모르는 값은
`null`이다. provider가 usage를 반환하지 않은 테스트/로컬 실행에서는 토큰과 모델 ID가
`null`일 수 있다. 가격표가 설정되지 않았으므로 비용은 기본적으로 `null`이다.

## Errors

| HTTP | 상황 |
| --- | --- |
| 401 | 내부 토큰 누락/불일치 |
| 422 | UUID, Enum, History sequence, 필수 필드 검증 실패 |
| 503 | LLM 설정, pgvector 검색, 생성 실패 |
| 504 | 내부 요청 또는 LLM timeout |

오류 응답에는 사용자 질문이나 내부 토큰을 포함하지 않는다. `requestId`는 유효한
요청 DTO까지 파싱된 경우에만 애플리케이션 로그의 추적 키로 사용한다.

## curl smoke test

```bash
curl -X POST http://localhost:8000/internal/v1/tutor/answer \
  -H 'Content-Type: application/json' \
  -H "X-Internal-API-Key: ${INTERNAL_API_TOKEN}" \
  -d '{
    "requestId":"aafb8e7b-1e15-428e-8a7d-e746c4aa9c04",
    "conversationId":"60fa8bac-b124-49bc-b8e0-393b611bc34b",
    "userId":"e66e192d-fcae-4575-9c7c-3d2b83f4b5ab",
    "question":"기준금리가 뭐야?",
    "modelTier":"BASIC",
    "history":[],
    "context":null,
    "knowledgeScope":{"conceptCodes":[]}
  }'
```

실제 LLM/DB 없는 테스트에서는 `get_tutor_service`를 Fake pipeline으로 override한다.
운영 설정에서 LLM 키가 없을 때 내부 API가 오프라인 답변을 성공 응답으로 위장하지
않고 `503`을 반환하는지 확인한다.

## Compatibility

기존 `POST /api/tutor/chat`은 삭제하지 않았다. 이 endpoint의 snake_case DTO와
프로세스 내 History는 기존 클라이언트/테스트 호환용이며, Node.js ERD 저장 경로에는
사용하지 않는다.
