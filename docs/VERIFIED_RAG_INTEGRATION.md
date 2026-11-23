# Verified RAG 데이터 경계

## 처리 흐름

Backend가 `conceptCode` 또는 `conceptId`를 기준으로 다음을 확인한 뒤
`verifiedContext`를 AI 내부 튜터 요청에 포함한다.

1. 공개된 개념과 개념 검수 이력 확인
2. `sourceDocumentIds`에 있는 모든 `ai.rag_documents` 확인
3. 문서 `review_status=approved` 및 라이선스 검수 승인 상태 확인
4. 선수 관계의 `review_status=APPROVED`, `reviewed_by`, `reviewed_at` 확인
5. 모든 검증을 통과한 문서 ID만 RAG 검색 범위로 전달

검증에 실패하면 `verificationStatus=BLOCKED`가 전달되고, AI는 검색과 답변
생성을 보류한다. 검색 백엔드가 문서 ID 범위를 지원하지 않으면 검증 요청에
대해 결과를 반환하지 않는다. 따라서 전역 fallback도 승인된 문서와 전달된
문서 범위를 벗어날 수 없다.

## 근거 추적

검색 결과는 `documentId`, `chunkId`, `version`, `reviewStatus`,
`licenseReviewStatus`를 유지한다. 인덱싱 단계에서도 승인되지 않은 검수·라이선스
상태의 문서는 거부한다.

## 데이터 검증

```bash
.venv/bin/python scripts/validate_economic_curation.py
```

기본 입력은 `data/curation/2026-11-23/`이며 JSON과 Markdown 보고서를
`reports/`에 생성한다. 해당 디렉터리 또는 12개 파일이 없으면 상태는
`BLOCKED`이고, 원본 데이터나 검수 상태를 만들거나 변경하지 않는다.

## 운영 전제

- 문서 라이선스 검수와 콘텐츠 검수는 별도로 승인되어야 한다.
- CSV의 `APPROVED` 표시는 Backend DB의 검수 이력 확인 전에는 승인으로 사용하지 않는다.
- 실제 pgvector/RDS와 외부 모델 품질·지연 평가는 staging에서 별도로 수행해야 한다.
