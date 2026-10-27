# C0704 문서 선별 보고서

기준일: 2026-10-27

## 실행 상태

`terms_approved.jsonl`, `terms_needs_review.jsonl`, `curriculum_full.json`이 작업 트리에 없어 통합 데이터 기준 C0704 후보를 생성하지 않았다. 따라서 후보 수, BOK/KDI 비율, Precision/Recall은 `NOT_AVAILABLE` 또는 `NOT_EVALUATED`다.

기존 `data/bok_terms_2026_rag.jsonl`의 문서 ID를 통합 데이터셋 ID로 추정하거나 자동 매핑하지 않았다. 특히 참고문헌 ID와 RAG `document_id`의 자동 매칭도 수행하지 않았다.

## 구현된 선별 규칙

`python -m scripts.select_concept_documents`는 다음 키워드·별칭을 기존 approved JSONL에서만 검색한다.

- 인플레이션, 디플레이션, 디스인플레이션
- 물가상승, 물가하락, 물가상승률, 가격수준
- inflation, deflation, disinflation

직접 핵심 용어가 정의·본문에 등장하면 `DIRECT`, 물가 관련 표현만 있으면 `INDIRECT`, `인플레이션감축법(IRA)`만 매칭되는 경우 `EXCLUDE`로 표시한다. 결과는 확률이 아니며 사람 검수 전까지 모두 `PENDING`이다.

## 출력 구조

파일이 제공되면 다음이 생성된다.

- `outputs/c0704/mapping_candidates.jsonl`
- `outputs/c0704/review_queue.csv`
- `outputs/c0704/evaluation_status.json`

파일이 없을 때는 `evaluation_status.json`만 `NOT_AVAILABLE`로 생성하며, 승인 매핑이나 가짜 후보를 만들지 않는다.

## 평가

사람이 검수한 100~200개 Gold Label이 준비되기 전에는 Precision, Recall, F1, TP, FP, FN을 계산하지 않는다. Keyword Only, Keyword+LLM, Vector, Hybrid 비교 코드는 Gold Label을 받은 뒤 연결할 수 있도록 `app/evaluation/relevance.py`에 준비했다.

문제 생성 쪽은 `app/services/question_generation.py`에서 승인된 근거가 없으면 `BLOCKED_NO_APPROVED_EVIDENCE`, 근거와 blueprint가 있으면 `DRAFT_READY`만 반환한다. 실제 LLM 호출·문제 승인·채점·보상은 수행하지 않는다.
