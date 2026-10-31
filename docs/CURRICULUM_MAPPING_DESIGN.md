# 커리큘럼-문서 매핑 설계

## 범위

전체 커리큘럼의 구조를 검증하되 실제 선별·검수 대상은 `R07 / C0704 / R07_S04` 하나로 제한한다.

- Topic: 물가와 인플레이션
- Concept: 인플레이션·디플레이션
- Required prerequisite: `C0701`
- Recommended prerequisite: `C0703`
- 학습 목표: 물가상승·물가하락과 물가상승률 둔화를 구별

필수 edge는 source를 먼저 배우는 방향으로만 검사한다. recommended edge는 차단 조건으로 사용하지 않으며, topic unlock 정책을 prerequisite에서 추론하지 않는다.

## 문서와 청크

통합 JSONL의 한 줄은 하나의 원문 Document다. 인덱싱 시 기존 `DocumentIndexer`가 긴 문서를 SentenceSplitter로 분할하고 실제 생성된 node ID를 `chunk_id`로 보존한다. 후보 선별 단계에서 청크가 제공되지 않으면 `chunk_id=null`을 유지하며 임의 ID를 만들지 않는다.

## 후보 → 검수 → 승인

1. 키워드·별칭으로 후보를 만든다.
2. 직접 관련/간접 관련/제외/판단 보류를 구분한다.
3. `review_queue.csv`에서 사람이 본문과 출처를 확인한다.
4. `review_status=PENDING`을 유지한다.
5. 사람이 승인한 문서만 문제 생성 근거와 승인 매핑에 사용한다.

자동 분류 결과는 정답 라벨이 아니다. LLM 분류는 provider와 호출 승인이 있을 때만 연결하며, 현재 구현은 dry-run 인터페이스만 제공한다.

## 문제 생성과 Tutor 분리

문제 생성은 승인된 근거 청크와 C0704의 기존 question blueprint를 입력으로 받아 `DRAFT` 문제를 만든다. Tutor는 질문·history를 Query Rewrite 후 기존 Retriever와 Grounding/Citation 검증을 통과한 답변만 반환한다. 채점, 보상, HP 및 Stage 완료는 Node.js 백엔드 책임이다.
