# AI Tutor ERD와 FastAPI 책임 매핑

## 소유권

| 영역 | Node.js Backend | FastAPI AI 서버 |
| --- | --- | --- |
| 인증/사용량 | JWT, 권한, 일일 한도, 중복 요청 예약 | 내부 서비스 토큰 검증 |
| 대화 저장 | `ai_conversations`, `ai_messages` | 저장하지 않음. 요청의 History를 읽기 전용으로 사용 |
| 출처/요청 저장 | `ai_message_sources`, `ai_requests` | 검색 결과와 Usage를 응답으로 반환 |
| 지식베이스 | 학습 콘텐츠 계약/배포 | RAG 문서·청크, 임베딩, pgvector |
| 추론 | AI 서버 호출 | Query Rewrite, Retrieval, LLM, Grounding |

FastAPI의 내부 경로는 `ConversationRepository`를 호출하지 않는다. `conversationId`와
`userId`는 Node.js가 생성·검증하여 전달하고, Node.js는 응답의 `requestId`, `sources`,
`usage`를 자신의 네 테이블에 저장한다. 기존 `/api/tutor/chat`은 하위 호환용으로
유지되지만 운영 연동 경로가 아니며 프로세스 내 임시 History만 사용한다.

## ERD 필드 매핑

### `ai_conversations` (Node.js 소유)

FastAPI 요청의 `conversationId`, `context.entryPoint`, `topicId`, `stageId`,
`conceptId`, `questionId`, `attemptId`, `summary`, `summaryUntilSeq`를 추론 컨텍스트로
사용한다. FastAPI가 conversation row를 생성하거나 수정하지 않는다.

### `ai_messages` (Node.js 소유)

요청 `history[].sequenceNo`, `history[].role`, `history[].content`를 읽고, 실제로
사용한 첫 sequence를 `response.historyFromSeq`로 반환한다. 재구성 질문은
`rewrittenQuery`로 Node.js가 저장할 수 있다.

### `ai_message_sources` (Node.js 소유)

응답 `sources[]`의 `documentId`, `documentVersion`, `chunkId`, `titleSnapshot`,
`conceptCode`, `rank`, `relevanceScore`를 그대로 저장할 수 있다. Source는 실제 검색
결과이면서 승인된 문서에서만 생성된다.

### `ai_requests` (Node.js 소유)

응답 `requestId`와 `usage`의 모델, 토큰, 지연시간, cache 여부, retrieval 전략,
비용 필드를 저장한다. 비용 가격표가 설정되지 않은 경우 `estimatedCost`와 `currency`는
`null`이다. 추정값을 실제 provider usage로 가장하지 않는다.

## ai 스키마 테이블 (FastAPI가 읽고 쓰는 테이블)

DB 구조의 기준은 백엔드 레포 `database/sql/init/02~04`다 (ai 스키마, 소유자 `ai_user`).
FastAPI는 `rag_documents`, `rag_document_chunks`, `rag_index_configurations`와
벡터 테이블 `data_projectteam02`에 데이터를 적재·검색만 하고, 운영(RDS)에서는
테이블을 만들지 않는다 (`VECTOR_STORE_PERFORM_SETUP=false`). `create_tables()`는
로컬 일회용 DB 전용이다.

대화·메시지·근거·요청·요약·장기 메모리(`tutor` 스키마)는 Node.js 백엔드 소유이며,
이 레포에는 해당 모델과 migration을 두지 않는다. 예전 `migrations/001~005`와
`/api/memory`, `ai.ai_user_memories`는 정리했다 (RDS의 빈 테이블은 2026-11-14 삭제).

## 흐름

```text
Node.js JWT/사용량/History
        │  POST /internal/v1/tutor/answer + 내부 토큰
        ▼
FastAPI DTO 검증 → bounded History/Summary
        → Query Rewrite → LlamaIndex/pgvector Retrieval
        → Context + LLM → Citation/Grounding 검증
        ▼
requestId + rewrittenQuery + sources + usage
        │
        └─ Node.js가 ai_messages/ai_message_sources/ai_requests에 저장
```
