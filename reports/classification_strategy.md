# Leren LLM 정밀 분류 전략

## 현재 실행 상태

이 문서는 `configs/chapters.yaml`의 임시 인플레이션 챕터 정의와 실제
`data/processed/chunks.jsonl`을 대상으로 한 분류 준비 결과다. production
curriculum 파일은 저장소에서 확인되지 않아 챕터 ID를 최종 커리큘럼으로
간주하지 않는다.

- 키워드 후보: 3,545개 청크 중 143개 청크-챕터 쌍
- 후보 비율: 4.03%
- 미매칭 표본: 100건, 삭제하지 않음
- 예상 입력 토큰: 호출당 평균 510.22, 전체 72,961
- 예상 출력 토큰: 호출당 180, 전체 25,740
- 예상 총 토큰: 98,701
- 요청 속도 가정: 30 requests/minute, 약 4.77분
- 실제 LLM 호출: 0건
- API 비용: 가격이 확인되지 않아 계산하지 않음

비용 산정 결과는 [`classification_cost_estimate.json`](pipeline/classification_cost_estimate.json)에
있다. 모델 가격은 확인 전까지 `null`로 유지하며, 설정 파일에 임의의 가격을
넣어 실제 가격처럼 보고하지 않는다.

## 처리 순서

1. chapter 정의, 포함·제외 조건, keyword, rubric 버전을 입력한다.
2. keyword로 넓은 후보를 만든다. 이 결과는 관련성 확정이나 정답 라벨이 아니다.
3. 후보 청크와 챕터 정의를 LLM 입력으로 만든다.
4. LLM은 0~1 관련도 점수, 판단 이유, 하위 주제, 원문 근거 구간을 반환한다.
5. 모델 출력에는 `model_name`, `classified_at`, `prompt_version`, `rubric_version`을 기록한다.
6. 근거 부족·경계 사례는 `needs_review=true` 및 `PENDING` 검수 큐로 보낸다.
7. 사람이 `APPROVED`, `REJECTED`, `NEEDS_REVISION`으로 판정한 뒤 용도별 정책에 반영한다.

## 출력 계약

기계 판독 스키마는 [`llm_classification_output_schema.json`](pipeline/llm_classification_output_schema.json)과
`app/dataset_pipeline/classification.py`에 있다. `relevance_score`는 모델이
정한 rubric 점수이며 확률·정확도·통계적 confidence로 해석하지 않는다.

한 청크가 여러 챕터에 속할 수 있도록 결과 key를 `chunk_id + chapter_id`로
취급한다. 원문 청크는 변경하지 않고 분류 결과를 sidecar로 저장한다.

## 평가 원칙

사람의 gold label이 없으면 Precision, Recall, F1을 산출하지 않는다. 후보 전체와
키워드 미매칭 표본을 사람이 검수하고 `PENDING → APPROVED/REJECTED/NEEDS_REVISION`
상태를 확정한 후, 임계값별 confusion matrix와 챕터별 metric을 계산한다.
챕터 정의나 rubric 버전이 바뀌면 기존 점수의 재사용 가능성을 자동으로 가정하지
않고 재분류 대상으로 표시한다.
