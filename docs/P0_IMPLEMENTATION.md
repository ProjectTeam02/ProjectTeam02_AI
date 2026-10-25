# Leren 2.0 Multi-turn RAG P0 구현 기록

## 구현 범위

- Python 3.12, FastAPI, async SQLAlchemy, LlamaIndex 0.14 계열
- PostgreSQL 영속 conversation/message/source와 소유권 검사
- request ID 기반 멱등성, conversation row lock, 순차 message 번호
- history token/message 예산과 지시대명사 후속 질문 rewrite
- PGVectorStore 재사용, Top-K 설정, approved/concept/stage metadata filter
- manifest 기반 정제·중복 방지·재인덱싱·embedding 설정 불일치 검사
- 근거 문서 ID/청크 ID 검증, 승인 상태 확인, 최소 claim overlap 검사
- 기존 `/api/tutor/chat`와 신규 `/internal/v1/tutor/answer`
- Recall@K/MRR 및 single-turn/multi-turn 비교 함수

## 데이터 흐름

```text
Node.js service auth + user/stage validation
  -> FastAPI internal DTO validation + requestId
  -> owned conversation/history load
  -> context-dependent query rewrite
  -> LlamaIndex PGVectorStore search
       review_status=approved AND concept_id AND stage_id
  -> bounded context (question, rewrite, stage/concept, documents, recent history)
  -> Korean tutor answer generation
  -> citation identity + approval + lexical support validation
  -> atomic user/assistant/source persistence
  -> answer, citations, grounded, conversationId, requestId
```

검색 장애, DB 장애, embedding 설정 오류는 빈 검색/메모리 성공으로 바꾸지 않습니다.
Generation이 실패하면 해당 turn은 저장하지 않습니다. LlamaIndex vector table이 실제
embedding 저장소이고 `rag_document_chunks`는 청크 감사용 registry이므로 그곳의 기존
`embedding` 열에는 새 embedding을 이중 저장하지 않습니다.

## DB migration

`001`부터 `004`까지 파일명 순서로 실행합니다. `004_multiturn_rag_p0.sql`은 기존 행을
삭제하지 않고 다음을 추가합니다.

- `ai_conversations`: stage/concept/status
- `ai_messages`: sequence/request/status/grounded와 UNIQUE 제약
- `ai_message_sources`: 답변 당시 source/document/version/title/URL snapshot
- `rag_documents`: source/concept/stage/review/license/date metadata
- `rag_index_configurations`: collection별 provider/model/dimension

운영 DB의 기존 테이블 이름·ID 타입·migration 도구를 Node.js 팀과 먼저 비교해야
합니다. 이 SQL은 DROP/TRUNCATE를 수행하지 않습니다.

## 내부 API 예시 응답

아래 값은 구조 예시이며 실제 답변이나 실제 출처가 아닙니다.

```json
{
  "conversationId": "generated-uuid",
  "answer": "검색된 검수 자료에 근거한 답변",
  "citations": [
    {
      "sourceId": "SOURCE-STABLE-ID",
      "documentId": "DOCUMENT-STABLE-ID",
      "documentVersion": "2026-01",
      "title": "검수된 문서 제목",
      "url": "https://official.example/document"
    }
  ],
  "grounded": true,
  "requestId": "request-001",
  "modelName": "configured-model",
  "usage": null
}
```

`question`과 기존 명세의 `userQuestion`을 입력 alias로 모두 받습니다. 응답은 camelCase
입니다. 401은 서비스 인증, 403은 conversation 소유권, 404는 conversation 없음,
422는 DTO 오류, 503은 LLM/embedding/retrieval/설정 장애입니다. Node.js가 timeout,
retry, 429 quota, 사용량 차감과 실패 복구를 담당합니다.

## 테스트와 평가

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m ruff check .
```

외부 서비스가 없는 테스트는 첫 질문/후속 질문, rewrite, 주제 전환, 사용자 격리,
빈 검색, 생성 실패, context 예산, 가짜 citation, 낮은 claim overlap, 승인/concept/stage
필터, 내부 camelCase 계약, request 멱등성, manifest, Recall@K/MRR을 검사합니다.
`app/evaluation/rag_metrics.py`의 `compare_runs`는 같은 relevance label에 대해 일반
검색과 multi-turn rewrite 검색을 비교합니다. notebook은 운영 코드를 import하는 최소
예제만 포함합니다.

## Node.js 팀과 확정할 계약

1. ID를 UUID로 고정할지 Long/string을 허용할지
2. `question` 대 `userQuestion`, citation 필드, nullable, 공통 envelope 적용 여부
3. `requestId`를 전역 유일 UUID로 보장하고 retry 시 재사용할지
4. service token 전달 방식, secret rotation, 내부 ingress 차단
5. Node timeout/retry 횟수와 503/504 매핑, 실패 시 quota 복구
6. stage/concept 접근권한과 wrong-answer context 검증 주체
7. AI DB를 공유할지 분리할지, migration 소유권과 배포 순서
8. 모델 usage/cost 로그 전달·보존 기간과 개인정보 제거 정책

## 외부 협의/미검증 위험

- KOSIS, OpenDART, World Bank, 공공기관 자료는 API 권한·라이선스·갱신 주기와
  review workflow가 확정되지 않아 자동 수집하지 않았습니다.
- 임시 PostgreSQL 18 클러스터에서는 migration 001~004, deterministic embedding
  인덱싱, pgvector 필터 검색, 2-turn 대화와 source 저장까지 통과했습니다. 다만 이 작업
  환경에는 Docker와 Python 3.12 실행 파일이 없어 Compose의 PostgreSQL 16 경로와
  Python 3.12 실행은 추가 검증해야 합니다. 현재 `.venv`는 Python 3.14라 발생한 경고를
  지원 버전 증거로 간주하지 않습니다.
- OpenAI key/승인 corpus가 없어 유료 LLM 호출, 실제 embedding 품질, latency/cost,
  한국어 답변 정성 평가는 수행하지 않았습니다.
- claim overlap은 보수적인 경량 1차 검사이지 의미론적 사실 검증기가 아닙니다.
  P1에서 평가셋과 NLI/LLM judge(비용·오류 분석 포함)를 비교해야 합니다.
- 동시 retry는 메시지 중복을 UNIQUE로 차단하지만, 동시에 생성된 빈 conversation이
  하나 남을 수 있습니다. 대규모 운영 전 별도 request ledger/cleanup 정책이 필요합니다.
