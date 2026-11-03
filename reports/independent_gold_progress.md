# 독립 Gold 검수 진행 현황

## 현재 상태

최종 평가 상태는 **NOT_EVALUATED**입니다. 템플릿은 생성되었지만 사람의
독립 검수와 합의가 완료되지 않았으므로 Precision·Recall·F1을 계산하지
않습니다.

| 기관 | 현재 검수 큐 행 | 핵심 상태 |
|---|---:|---|
| KDI | 160 | 현재 320건 큐의 development/test 표본 |
| BOK | 160 | 현재 320건 큐의 development/test 표본 |

현재 평가 기준은 `data/labeled/precision/independent_gold_review_queue.csv`의
KDI 160건+BOK 160건이다. 과거 `reports/step3`의 KDI 160건+BOK 205건
템플릿은 레거시로 보존하지만 현재 큐·Gold 조립·평가에 혼용하지 않는다.

## 과거 표본 버전 주의

기존 `reports/step3`의 160/205건 템플릿은 현재 canonical export와 source
구성이 다르므로 재사용하지 않았습니다. 이전 행의 라벨이나 승인 상태를 현재
데이터에 복사하지 않았습니다. 상세 대조 결과는
`reports/gold_template_reconciliation.md`에서 확인합니다.

## 사람이 해야 할 일

1. KDI와 BOK 행의 원문 및 C0704 기준을 보고 평가자 A/B가 독립적으로 0·1·2를 입력합니다.
2. `final_gold`는 합의 또는 제3자 검수 후에만 입력합니다.
3. `evidence_quote`, `reason`, `review_status`, `reviewer_count`, `review_mode`를 채웁니다.
4. `test` 행은 프롬프트·키워드·임계값 조정에 사용하지 않습니다.
5. 모든 방법이 동일한 test 문서 ID에 대해 예측을 만든 뒤에만 비교 실험을 실행합니다.
