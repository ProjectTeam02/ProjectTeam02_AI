# Gold 입력 템플릿 조정 보고서

- 상태: **`PASS`**
- 현재 기준: **KDI 160 + BOK 160 = 320건**
- 현재 큐: `data/labeled/precision/independent_gold_review_queue.csv` (320건, 기관별 `{'BOK': 160, 'KDI': 160}`)
- 과거 KDI 템플릿: `reports/step3/kdi_independent_gold_review_template.csv` (160건, 기관별 `{'BOK': 160}`) → **LEGACY_EXCLUDED**
- 과거 BOK 템플릿: `reports/step3/bok_independent_gold_review_template.csv` (205건, 기관별 `{'BOK': 205}`) → **LEGACY_EXCLUDED**

현재 검수 CLI와 Gold 조립 스크립트의 기본 입력은 현재 320건 큐이며, 과거 템플릿은 명시적인 레거시 점검 시에만 사용할 수 있습니다.
