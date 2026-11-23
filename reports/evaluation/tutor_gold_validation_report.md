# Tutor Gold 검증 보고서

- 검증 시각: 2026-11-23T13:34:09.960154+00:00
- 입력: `/Users/a1/Desktop/산학프로젝트 /ProjectTeam02_AI/data/evaluation/tutor_test_100.jsonl`
- 구조 검증: `PASS`
- 최종 평가 사용 가능: `BLOCKED`
- 자동 독립 승인 수행 여부: `False`

## 현황

- 전체 건수: 100
- 상태별: `{"PENDING_REVIEW": 100}`
- 검수 큐 상태: `{"REVIEW_REQUIRED": 100}`
- conceptCode 누락: 100건
- approvedEvidence 포함 행: 0건
- 차단 finding: 600건
- curation 입력 상태: `BLOCKED`

## 미완료 입력

- canonical Backend conceptCode mapping file
- independent human review and adjudication
- approved evidence with confirmed source/license status

## 차단 사유 샘플

- `{"caseId": "TUTOR-001", "code": "CONCEPT_CODE_MISSING"}`
- `{"caseId": "TUTOR-001", "code": "SOURCE_REVIEW_REQUIRED", "sourceId": "kdi_dic_584"}`
- `{"caseId": "TUTOR-001", "code": "LICENSE_REVIEW_REQUIRED", "sourceId": "kdi_dic_584"}`
- `{"caseId": "TUTOR-001", "code": "INDEPENDENT_REVIEW_REQUIRED"}`
- `{"caseId": "TUTOR-001", "code": "DATASET_VERSION_MISSING"}`
- `{"caseId": "TUTOR-001", "code": "GOLD_VERSION_MISSING"}`
- `{"caseId": "TUTOR-002", "code": "CONCEPT_CODE_MISSING"}`
- `{"caseId": "TUTOR-002", "code": "SOURCE_REVIEW_REQUIRED", "sourceId": "kdi_dic_317"}`
- `{"caseId": "TUTOR-002", "code": "LICENSE_REVIEW_REQUIRED", "sourceId": "kdi_dic_317"}`
- `{"caseId": "TUTOR-002", "code": "INDEPENDENT_REVIEW_REQUIRED"}`
- `{"caseId": "TUTOR-002", "code": "DATASET_VERSION_MISSING"}`
- `{"caseId": "TUTOR-002", "code": "GOLD_VERSION_MISSING"}`
- `{"caseId": "TUTOR-003", "code": "CONCEPT_CODE_MISSING"}`
- `{"caseId": "TUTOR-003", "code": "SOURCE_REVIEW_REQUIRED", "sourceId": "kdi_dic_1977"}`
- `{"caseId": "TUTOR-003", "code": "LICENSE_REVIEW_REQUIRED", "sourceId": "kdi_dic_1977"}`
- `{"caseId": "TUTOR-003", "code": "INDEPENDENT_REVIEW_REQUIRED"}`
- `{"caseId": "TUTOR-003", "code": "DATASET_VERSION_MISSING"}`
- `{"caseId": "TUTOR-003", "code": "GOLD_VERSION_MISSING"}`
- `{"caseId": "TUTOR-004", "code": "CONCEPT_CODE_MISSING"}`
- `{"caseId": "TUTOR-004", "code": "SOURCE_REVIEW_REQUIRED", "sourceId": "kdi_dic_816"}`
- `{"caseId": "TUTOR-004", "code": "LICENSE_REVIEW_REQUIRED", "sourceId": "kdi_dic_816"}`
- `{"caseId": "TUTOR-004", "code": "INDEPENDENT_REVIEW_REQUIRED"}`
- `{"caseId": "TUTOR-004", "code": "DATASET_VERSION_MISSING"}`
- `{"caseId": "TUTOR-004", "code": "GOLD_VERSION_MISSING"}`
- `{"caseId": "TUTOR-005", "code": "CONCEPT_CODE_MISSING"}`
- `{"caseId": "TUTOR-005", "code": "SOURCE_REVIEW_REQUIRED", "sourceId": "kdi_dic_2579"}`
- `{"caseId": "TUTOR-005", "code": "LICENSE_REVIEW_REQUIRED", "sourceId": "kdi_dic_2579"}`
- `{"caseId": "TUTOR-005", "code": "INDEPENDENT_REVIEW_REQUIRED"}`
- `{"caseId": "TUTOR-005", "code": "DATASET_VERSION_MISSING"}`
- `{"caseId": "TUTOR-005", "code": "GOLD_VERSION_MISSING"}`
- 그 외 570건은 JSON 보고서에 기록

## 정책

- REVIEW_REQUIRED 행은 정식 모델 비교·교육 품질 점수에 사용하지 않는다.
- 출처 승인, 라이선스, 개념 코드, 독립 검수 이력은 사람이 확인해야 한다.
- 정답 초안은 별도 검수 큐에만 기록하며 Gold 승인으로 간주하지 않는다.
- 원본 JSON/JSONL과 운영 DB는 수정하지 않았다.
