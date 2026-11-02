# 멘토 피드백 반영 및 진행 보고

## 실제 실행 결과

- 현재 로컬 canonical 문서: KDI 2,750건 + BOK 789건 = 3,539건
- 입력 파일: JSON/JSONL 4개. 기관별 JSONL을 canonical으로 선택해 미러 중복을 세지 않음
- 전체 문서 토큰: 770,607개, 평균 217.75개, 중앙값 195개, p95 449개
- 청크: 3,539개 문서 → 3,545개 청크
- 키워드 후보: 3,545개 청크 중 143개, 4.03%
- 미매칭 표본: 100개 생성
- LLM 호출: 0건, DB 쓰기: 0건

## 발견한 품질·추적성 문제

1. BOK canonical RAG 레코드 789건에 source URL이 없다. page locator는 있으므로 URL 또는 원문 식별자를 보강해야 한다.
2. 현재 canonical 레코드에는 source review status와 license 승인 필드가 없어 3,539건 모두 운영 승인으로 해석할 수 없다.
3. source ID와 text hash는 기관 내부 dedup key로 사용할 수 있지만, 동일 본문이어도 KDI와 BOK 출처는 자동 병합하지 않는다.
4. 7개 문서가 20토큰 미만이고, 6개 문서가 700토큰을 초과한다. 짧은 용어 정의는 유지하고 긴 문서만 token-aware split했다.
5. source RAG 텍스트와 원본 JSON definition은 BOK에서 포맷이 달라, JSON/JSONL duplicate audit는 ID 일치와 내용 일치를 별도 기록해야 한다.
6. production curriculum 파일이 없어 `configs/chapters.yaml`은 `DRAFT_NOT_CANONICAL` 임시 rubric이다.

## 구현한 기능

- `app/dataset_pipeline/io.py`: 기관별 파일 탐색, JSON/JSONL mirror audit, 정규화, dataset version
- `app/dataset_pipeline/tokenizer.py`: tiktoken exact token count
- `app/dataset_pipeline/chunks.py`: paragraph-first/token-aware chunking과 lineage metadata
- `app/dataset_pipeline/keywords.py`: 설정 기반 키워드 후보·미매칭 표본
- `app/dataset_pipeline/classification.py`: LLM prompt와 JSON output contract 검증
- `scripts/run_eda.py`, `make_chunks.py`, `keyword_filter.py`, `estimate_classification_cost.py`
- Matplotlib 시각화 6종, 정규화 문서·청크·후보 JSONL/CSV, 비용 추정 JSON
- Task B 문제 생성과 Tutor Multi-turn RAG 워크플로우 설계 문서

## 아직 실행하지 않은 작업

- 실제 LLM 대량 분류 및 모델 간 일관성 평가
- 사람 gold label 기반 Precision/Recall/F1
- license·출처 권한 검토와 최종 chapter mapping 승인
- PostgreSQL/pgvector 적재·재색인
- 문제 생성, 문제은행 게시, Node.js API 연동
- production curriculum에 따른 임시 chapter rubric 교체

## 다음 단계와 확인 요청

1. production curriculum의 canonical `chapter_id/concept_id/stage_id`와 학습목표를 제공받는다.
2. BOK source URL 또는 공식 원문 locator와 KDI 이용 허가·attribution 정책을 확인한다.
3. 143개 후보와 100개 미매칭 표본을 최소 2인 검수해 gold label을 만든다.
4. 관련도 임계값별 문제 생성 후보 수와 Tutor 후보 재현율을 비교한다.
5. 모델·가격·요청 속도를 확정한 뒤 소규모 LLM 샘플 호출을 승인한다.
