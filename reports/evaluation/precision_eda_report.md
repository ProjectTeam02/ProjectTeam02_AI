# Leren precision EDA 실행 보고서

## 1. 연구 개요

인플레이션 챕터 문서 선별을 위해 KDI·BOK 라벨링 표본과 canonical corpus를 연결하고 Keyword-only, LLM-only, Hybrid 결과를 비교했다.
문제 생성은 관련도 2, Tutor 선별은 관련도 1 또는 2를 양성으로 보는 별도 정책을 사용한다.

## 2. 데이터셋 및 검증

- 전체 corpus: 3539건; KDI/BOK: {'BOK': 789, 'KDI': 2750}
- 라벨링 표본: 320건; 기관별: {'KDI': 160, 'BOK': 160}
- dataset_version: `50047d6bd740671252df664aba2ee0bbac845bbf68addbc4f90d6c5efe8e7d0d`; chunk: 3545개; token: 770,607개
- 원본 Excel은 읽기 전용이며, BOK `확정 골드=완료`는 숫자 Gold로 변환하지 않았다.
- 전체 corpus 품질 검토는 Notebook 실행 시점의 `full_dataset_validation.json`을 함께 참조한다.
- BOK source_url 누락: 789건; license 미확정: 3539건
- 20토큰 미만: 7건; 청크 제한 초과: 6건; 동일 본문 hash 그룹: 1건

## 3. 라벨링 및 A/B 일치도

A/B 수치는 독립 인간 평가자 간 일치도가 아닌 `AI_REVIEW_AGREEMENT`로만 해석한다.

| 기관 | 비교 | 일치 | 불일치 | 일치율 | Kappa |
|---|---:|---:|---:|---:|---:|
| KDI | 49 | 39 | 10 | 0.7959 | 0.5429 |
| BOK | 160 | 68 | 92 | 0.4250 | 0.1359 |
| ALL | 209 | 107 | 102 | 0.5120 | 0.2579 |

B 재검토 대상: 전체 71건 (KDI 50건, BOK 21건), 그중 A/B 불일치: 전체 26건 (KDI 10건, BOK 16건). 두 수치는 별도 개념이다.

## 4. 방법별 실행 결과

| 방법 | 상태 | 평가 문서 | 주요 결과 |
|---|---|---:|---|
| Keyword-only | EXECUTED_OFFLINE | 320 | 후보 51건 (15.9%) |
| LLM-only | DRY_RUN_INCOMPLETE_PILOT | 10 | 파일럿 커버리지 3.1% |
| Hybrid | DRY_RUN_INCOMPLETE_PILOT | 274 | 관측 예측 274건 |

## 5. Precision / Recall / F1

독립 Gold 상태: `NOT_READY`, 건수: 0. 따라서 최종 Precision·Recall·F1은 `NOT_EVALUATED`이다.
현재 proxy 값은 Workbook/A-B 합의 참고 라벨과의 예비 일치도이며 최종 모델 성능으로 보고하지 않는다.

## 6. 한계 및 다음 개발

- Keyword/reference 판정 불일치 사례: 11건; 독립 Gold 전에는 오분류로 확정하지 않는다.
- 신규 API 호출: 0건; 저장된 파일럿만 재사용했다.
- 독립 Gold 승인 후 동일한 평가 모수로 두 목적별 TP/FP/FN/TN과 P/R/F1을 산출한다.
- 키워드 미적중 문서, 품질 검토필요 문서, A/B 불일치 문서를 독립 검수 표본에 포함한다.

## 7. 산출물

- `data/processed/evaluation/combined_320.jsonl`
- `reports/evaluation/label_disagreements.csv`
- `reports/evaluation/keyword_predictions.csv`
- `reports/evaluation/llm_predictions.csv`
- `reports/evaluation/hybrid_predictions.csv`
- `reports/evaluation/method_comparison.json`
- `reports/evaluation/precision_eda_report.md`
