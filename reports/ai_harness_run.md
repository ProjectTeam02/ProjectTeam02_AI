# AI workflow harness run

## 2026-11-10 local run

| 항목 | 기준선 | 구현 후 |
|---|---:|---:|
| 결정적 회귀 테스트 | 105 passed | 111 passed |
| Ruff | 기존 미확인 | passed |
| 외부 LLM 호출 | 0 | 0 |
| PostgreSQL/pgvector | 미연결 | 미연결 |

고정 모의 모델·고정 승인 근거로 다음 사례를 검증했다.

- 튜터 후속 질문(`그럼 CPI랑 무슨 관계야?`)의 query rewrite
- 검색 결과 없음과 검색/생성 장애의 분리
- 허위 citation 제거 및 실제 검색 결과 ID 대조
- 다른 사용자의 레거시 대화 접근 차단
- 최초 생성 이후 QV 수정 2회 한도
- 승인 근거 없는 실패 배치의 문항 미저장
- 동일 `requestId` 재제출의 단일 job/모델 호출 보장

문제 생성 성공 smoke test는 `POST /internal/v1/questions/jobs`에서 HTTP 202,
`executionStatus=COMPLETED`, `reviewStatus=PENDING_REVIEW`를 반환했고,
`GET /internal/v1/questions/jobs/{job_id}`에서 같은 job과 문항을 조회했다.
실패 smoke test는 `failureStep=evidence_lookup`,
`failureCode=INSUFFICIENT_EVIDENCE`, `result=null`을 반환했다.

실제 LLM 품질, 사람 검수 통과율, QV 누락 오류율, Recall@K/MRR, p95 지연,
모델 호출 수·비용은 외부 키와 운영 승인 corpus/pgvector가 이 환경에 없어
측정하지 않았다. 이 값들은 staging 평가셋과 사람이 검토한 기대 근거/허용
답변 기준으로 별도 실행해야 한다.
