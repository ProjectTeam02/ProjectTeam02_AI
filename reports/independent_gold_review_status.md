# 독립 Gold 검수 상태

## 현재 상태

- 평가 상태: **`NOT_EVALUATED`**
- 사유: 독립 합의 Gold가 아직 생성되지 않았습니다.
- 검수 큐: `data/labeled/precision/independent_gold_review_queue.csv`
- 검수 행 수: **320건**
- 개발셋/테스트셋: `{'development': 270, 'test': 50}`
- 출처 그룹: `['BOK', 'KDI']`
- 현재 입력의 BOK 포함 여부: **True**

## 독립성 보호 규칙

- 기존 평가자 A/B 및 확정 골드는 검수 큐에 복사하지 않았습니다.
- `gold_score`는 사람이 원문과 챕터 기준을 확인한 뒤 입력합니다.
- 합의 검수 2명 이상 또는 제3자 검수 1명 이상만 승인할 수 있습니다.
- `INDEPENDENT_APPROVED`와 `APPROVED`가 아닌 행은 최종 평가에서 제외됩니다.
- 테스트셋은 키워드·프롬프트·임계값 조정에 사용하지 않습니다.

## 검수 전 차단 상태

독립 Gold가 생성되기 전까지 세 방법의 Precision·Recall·F1과
최종 성능 지표는 `NOT_EVALUATED`로 유지됩니다. 일부 방법의 예측이
빠진 경우에도 교집합만으로 지표를 계산하지 않습니다.
