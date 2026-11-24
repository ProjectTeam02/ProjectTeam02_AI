# Personalized Tutor Context 결정 기록

## 범위

AI-TUTOR-02와 AI-TUTOR-07의 AI 서버 측 입력 Schema와 일회성 Context 연결만
구현한다. 사용자 학습 이력이나 개념 관계를 AI 저장소에 영속화하지 않는다.

## 현재 계약 상태

2026-11-17 기준 Backend `develop`의 Tutor 요청 DTO는 기존 `context`와
`knowledgeScope`만 허용하고 `personalizedContext`를 전달하지 않는다. 따라서 AI
서버의 필드는 선택적으로만 열려 있으며, Backend DTO와 Swagger 계약이 갱신되기
전까지 운영 요청에는 사용되지 않는다.

Backend의 현재 개념 선수관계 테이블에도 관계별 검수 상태가 확인되지 않았다.
AI는 이를 추정하지 않고, 입력 관계에 `approved`, `published`, 또는 `reviewed`가
명시된 경우에만 그래프 Context에 포함한다.

## 안전 정책

- 프로필, 진단 가설, 평가 기록, 교수 전략은 요청 범위 안에서만 사용한다.
- 미확정 오개념 가설은 확정 진단으로 표현하지 않는다.
- 검수된 RAG 근거가 개인화 값보다 우선한다.
- 그래프 깊이 2, 노드 20개, 그래프 400토큰을 기본 상한으로 둔다.
- 사용자별 상태를 전역 캐시나 AI DB에 저장하지 않는다.
- Backend가 0~100 퍼센트 값을 보낼 경우 변환 규칙 합의 전까지 수용하지 않는다.

## Backend 협업 필요 사항

`personalizedContext` 전달 여부, 각 필드의 필수성, 숙련도 단위, 개념 관계
검수 상태의 소유·값 목록을 Backend와 확정한 뒤 계약 테스트를 추가해야 한다.
