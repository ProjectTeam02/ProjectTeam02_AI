# AI ↔ Backend 튜터 응답 계약 (v1.0)

`POST /internal/v1/tutor/answer`의 **응답** 계약이다. 요청·인증·curl 예시는
[TUTOR_INTERNAL_API_CONTRACT.md](TUTOR_INTERNAL_API_CONTRACT.md)를 본다.

| 항목 | 기준 |
| --- | --- |
| 계약 버전 | `tutoringMeta.schemaVersion = "1.0"` (Backend는 다른 값을 거부) |
| AI 구현 | `app/schemas/tutor.py` `InternalTutorResponse` (Pydantic, OpenAPI `/openapi.json`에 노출) |
| Backend 검증 | `src/modules/tutor/dto/aiInternalResponse.dto.js`, `dto/tutorMetadata.dto.js`, `approvedSources.js` (develop `91d052e` 기준 대조) |
| 스키마 스냅샷 | [contracts/internal_tutor_response.schema.json](contracts/internal_tutor_response.schema.json), [contracts/internal_tutor_request.schema.json](contracts/internal_tutor_request.schema.json) |
| 골든 예시 | [contracts/examples/valid](contracts/examples/valid) (양쪽 모두 통과), [contracts/examples/invalid](contracts/examples/invalid) (양쪽 모두 거부) |
| 회귀 테스트 | `tests/test_tutor_contract.py` (CI), `scripts/check_backend_contract.sh <Back 경로>` (로컬·수동, Node 필요) |

원칙: **AI는 Backend가 거부할 값을 만들지 않는다.** Backend는 응답을 다시 검증하고,
어느 한 필드라도 맞지 않으면 저장하지 않고 앱에 `503`을 돌려준다. 그래서 AI 쪽
스키마는 Backend보다 느슨하면 안 되고, AI의 생성 코드는 형식이 불확실한 값을
실패시키지 않고 **버린다(Fail-Closed)**.

## 1. 최상위 필드

| 필드 | 타입 | 필수 | 규칙 |
| --- | --- | --- | --- |
| `requestId` | UUID | 예 | 요청의 `requestId`와 같아야 함 (다르면 Backend 503) |
| `answer` | string | 예 | 1자 이상 |
| `rewrittenQuery` | string | 예 | Backend는 `null`도 허용하지만 AI는 항상 문자열을 보냄 |
| `groundingStatus` | enum | 예 | `GROUNDED` \| `INSUFFICIENT` |
| `historyFromSeq` | int \| null | 아니오 | 1 이상 |
| `sources[]` | array | 아니오 | §4. `rank`는 1부터 고유 |
| `usage` | object | 예 | §5 |
| `tutoringMeta` | object \| null | 아니오 | §2. `TUTOR_METADATA_ENABLED=true`일 때만 Backend가 저장·노출 |
| `proposedAction` | object \| null | 아니오 | §3. Backend가 후보·소유권 재검증 후에만 저장 |

`groundingStatus` 의미:

- `GROUNDED`: 승인(`review_status=approved`) 문서 청크를 근거로 답변했고 인용 검증을 통과함.
- `INSUFFICIENT`: 승인 근거가 없거나 인용 검증 실패. `answer`는 거절·안내 문구이고 `sources`는 보통 `[]`.
  이 상태는 정상 응답(200)이다. 오류로 바꾸지 않는다.

## 2. `tutoringMeta`

미지(unknown) 키가 하나라도 있으면 Backend가 거부한다(중첩 객체 포함).

| 필드 | 규칙 |
| --- | --- |
| `schemaVersion` | 정확히 `"1.0"` |
| `conceptCode` | 1~30자 또는 `null` |
| `diagnosis.misconceptionType` | `KNOWLEDGE_GAP` \| `RELATION_ERROR` \| `CAUSAL_ERROR` \| `APPLICATION_ERROR` \| `UNCERTAIN` |
| `diagnosis.confidence` | 0~1. 근거 부족이면 `0` |
| `diagnosis.evidenceQuestionIds` | UUID 배열, 최대 20, 중복 금지(대소문자 무시). 근거 없으면 `[]` |
| `diagnosis.needsFollowup` | boolean |
| `diagnosis.reasoningSummary` | 1~500자, 사용자 표시용. 내부 추론 원문 금지 |
| `strategy.strategyId` / `strategyVersion` | 1~100자 / 1~50자 |

진단 정책: 오답 1회·질문 단위 근거 없음은 확정하지 않는다 → `UNCERTAIN`,
`confidence=0`, `needsFollowup=true` (`app/services/tutor_recommendation.py`).

## 3. `proposedAction`

| 필드 | 규칙 |
| --- | --- |
| `type` | `SOLVE_QUESTION` \| `START_STAGE` \| `REVIEW_CONCEPT` \| `CONTINUE_LEARNING` \| `NONE` |
| `conceptCode` | 1~30자 또는 `null` |
| `questionId` / `stageId` / `attemptId` | UUID 또는 `null` |
| `reason` | 1~500자 |
| `priority` | `HIGH` \| `MEDIUM` \| `LOW` |

| type | 필수 | 금지 |
| --- | --- | --- |
| `SOLVE_QUESTION` | `questionId`, `stageId`, `attemptId`, `conceptCode` (요청의 `eligibleQuestionCandidates` 중 하나와 4개 모두 일치) | — |
| `START_STAGE` | `stageId` | `questionId`, `attemptId` |
| `REVIEW_CONCEPT` | `conceptCode` | `questionId`, `attemptId` |
| `CONTINUE_LEARNING` | `stageId` 또는 `attemptId` | `questionId` |
| `NONE` | — | `questionId`, `stageId`, `attemptId` |

AI는 후보 목록 밖의 문항을 추천하지 않는다. 채점·보상·완료 상태는 Backend Quiz 서비스 소유다.

## 4. `sources[]`와 검수 상태 기준

| 필드 | 규칙 (Backend `SOURCE_LIMITS`) |
| --- | --- |
| `documentId` | 1~255자, 필수 |
| `documentVersion` | ≤100자 또는 `null` (AI가 잘라서 보냄) |
| `chunkId` | 1~255자, 필수 |
| `titleSnapshot` | ≤500자 또는 `null` (AI가 잘라서 보냄) |
| `conceptCode` | ≤30자 또는 `null` (초과 시 AI가 `null`로 보냄) |
| `rank` | 1~32767, 응답 내 고유 |
| `relevanceScore` | 0~1 또는 `null` |
| `reviewStatus` | **추적용(v1.0 추가)**. 검색 시점 문서 내용 검수 상태 스냅샷 |
| `licenseReviewStatus` | **추적용(v1.0 추가)**. 요청 `verifiedContext.sources[]`가 준 라이선스 검수 상태. 없으면 `null` |

호환성: Backend `source()`는 알려진 7개 필드만 골라 저장하므로 `reviewStatus`,
`licenseReviewStatus`는 **무시되고 깨지지 않는다**(develop `91d052e`에서 확인).
Grounding trace(문서/버전/청크/검수상태)를 응답 로그에서 바로 볼 수 있게 하려는 필드다.

적용 기준:

1. **내용 검수(`review_status`)** — 권한은 Backend에 있다.
   - AI: `verifiedContext`가 있으면 그 `sourceDocumentIds` 안에서 `review_status=approved` 문서만 근거로 쓴다. 승인 근거가 없으면 `INSUFFICIENT`.
   - Backend(#181 `assertApprovedTutorSources`): 인용된 모든 `documentId`를 `ai.rag_documents.review_status='approved'`로 재확인하고, 하나라도 아니면 503. AI가 보낸 `reviewStatus` 값은 판단에 쓰지 않는다.
2. **라이선스 검수(`license_review_status`)** — v1.0에서는 **차단 조건이 아니다.**
   - Backend `approvedSources.js`가 라이선스를 검사하지 않고, 현재 문서 대부분이 `PENDING`이라 지금 차단하면 모든 답변이 `INSUFFICIENT`가 된다.
   - AI는 값을 그대로 `licenseReviewStatus`에 실어 추적만 한다.
   - 외부 공개 전 라이선스 차단은 **"Backend 수정 후 도입"**: Backend가 `license_review_status='APPROVED'` 검사를 `assertApprovedTutorSources`에 추가하고, 같은 시점에 AI가 `verifiedContext.sources[].licenseReviewStatus != APPROVED` 문서를 검색 후보에서 제외한다. 이때 계약은 `1.1`로 올린다(§7).

## 5. `usage`

| 필드 | 규칙 |
| --- | --- |
| `modelId`, `embeddingModelId` | ≤100자 또는 `null` |
| `inputTokens`, `outputTokens` | 0 이상 정수 또는 `null` |
| `latencyMs` | 0 이상 정수, 필수 |
| `cacheHit` | boolean, 필수 |
| `retrievalStrategy` | 1~50자, 필수 |
| `estimatedCost` | 0 이상 또는 `null` |
| `currency` | `^[A-Z]{3}$` 또는 `null` |

## 6. 오류 규격

FastAPI는 `{"detail": ...}` 본문으로 오류를 돌려주고, Backend `fastapi.client.js`가 앱용 오류로 바꾼다.
앱에는 항상 Backend 공통 오류 형식(`SERVICE_UNAVAILABLE` 503)만 나간다.

| FastAPI 상태 | 원인 | Backend `reason` | 앱 응답 |
| --- | --- | --- | --- |
| 200 + 형식 위반 | §1~§5 위반 | (DTO `invalidField` 로그) | 503 |
| 200 + 미승인 출처 | Backend 재검증 실패 | — | 503 |
| 401 | 내부 토큰 누락/불일치 | `AI_HTTP_ERROR` | 503 |
| 404 / 403 | 대화 없음 / 접근 거부 | `AI_HTTP_ERROR` | 503 |
| 422 | 요청 스키마 위반(UUID, enum, history, 후보 ID 비UUID 등) | `AI_REQUEST_REJECTED` | 503 |
| 503 | LLM 설정, 검색, 생성 실패 | `AI_HTTP_ERROR` | 503 "AI 서버 요청에 실패했습니다." |
| 504 | 내부 요청 timeout(45초) | `AI_TIMEOUT` | 503 "튜터가 바쁩니다." |
| (연결 끊김) | Backend timeout(`FASTAPI_TIMEOUT_MS`) / 네트워크 | `AI_TIMEOUT` / `AI_UNREACHABLE` | 503 |

`FASTAPI_TIMEOUT_MS`는 AI 내부 제한(45초)보다 커야 AI의 504가 먼저 도착한다.

## 7. 버전 정책

- **호환 변경**(Backend가 무시하는 선택 필드 추가, 예: `sources[].reviewStatus`): `schemaVersion` 유지. 스냅샷·이 문서·골든 예시 갱신.
- **비호환 변경**(필수 필드 추가, enum 값 추가, 길이 축소, `tutoringMeta`/`proposedAction` 안 키 추가 — Backend가 미지 키를 거부): `schemaVersion`을 올리고 Backend가 새 버전을 먼저 수용한 뒤 AI를 배포한다. 롤백은 Backend `TUTOR_METADATA_ENABLED=false`.
- 계약이 바뀌는 PR은 다음을 함께 올린다: `scripts/export_tutor_contract.py` 재생성, 이 문서, 골든 예시, `scripts/check_backend_contract.sh` 실행 결과.

## 8. 검증 방법

```bash
.venv/bin/python -m pytest -q tests/test_tutor_contract.py     # 스냅샷·골든 예시 (CI)
.venv/bin/python scripts/export_tutor_contract.py --check     # 스냅샷 드리프트만
scripts/check_backend_contract.sh ../ProjectTeam02_Back origin/develop   # Backend DTO 대조
```

2026-11-28 실행 결과(Backend develop `91d052e`): valid 4건 ACCEPT, invalid 6건 REJECT(503) — 10/10 일치.
