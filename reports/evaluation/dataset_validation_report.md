# Tutor 평가 데이터셋 검증 보고서

- 생성 시각: 2026-11-22T13:32:50.157390+00:00
- 입력: `/Users/a1/Desktop/산학프로젝트 /ProjectTeam02_AI/data/evaluation/tutor_test_100.jsonl`
- 구조 검증: `PASS`
- 점수화 준비: `BLOCKED`

## 분포

- 전체 건수: 100
- 기관별: `{"BOK": 50, "KDI": 50}`
- 난이도별: `{"easy": 34, "hard": 33, "medium": 33}`
- 유형별: `{"A_CONCEPT_EXPLANATION": 20, "B_MISCONCEPTION_DIAGNOSIS": 25, "C_PERSONALIZED_LEARNING": 25, "D_MULTITURN_CONTEXT": 20, "E_INSUFFICIENT_EVIDENCE": 10}`
- 검수 상태별: `{"PENDING_REVIEW": 100}`

## 근거·계보 검증

- approvedEvidence 건수: 0
- 후보 근거 승인 상태: `{"UNKNOWN": 100}`
- conceptCode 누락: 100건
- 개인정보 탐지: 0건

## 오류

- 없음

## 주의 및 미완료 입력

- no evidence has an explicit approved status
- independent Gold review is not complete
- canonical source review status is unresolved for at least one source document
- canonical license status is unresolved for at least one source document

## 정책

- PENDING_REVIEW 행은 최종 모델 품질 점수에서 제외한다.
- `expectedConcepts`, `expectedMisconception`, `expectedTeachingBehavior`, `goldStatus`는 모델 입력에서 제외한다.
- source review/license/concept mapping이 승인되기 전에는 approvedEvidence로 승격하지 않는다.
