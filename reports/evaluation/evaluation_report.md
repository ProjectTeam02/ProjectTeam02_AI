# Leren KDI/BOK Classification Evaluation Report

## 1. 연구 개요

물가와 인플레이션 챕터의 문서 선별을 위해 기존 데이터 파이프라인에 KDI·BOK 라벨링 표본을 연결하고 Keyword-only, LLM-only, Hybrid의 재현 가능한 비교 실행 경로를 검증했다.
문제 생성은 관련도 2를, Tutor 후보 선별은 관련도 1·2를 양성으로 보는 별도 정책을 사용한다.

## 2. 데이터셋 및 파일 감사

- KDI: 160건; BOK: 160건; 통합: 320건
- canonical corpus: 3539건 ({'BOK': 789, 'KDI': 2750})
- dataset_version: `50047d6bd740671252df664aba2ee0bbac845bbf68addbc4f90d6c5efe8e7d0d`
- 중복 document_id: 0건; 잘못된 ID: 0건
- Excel 원본은 읽기 전용으로 처리했고, `확정 골드=완료`는 숫자 Gold로 변환하지 않았다.

## 3. 원본 대조 및 라벨 검증

원문 대조 상태는 EXACT_MATCH, NORMALIZED_MATCH, CONTENT_MISMATCH, SOURCE_NOT_FOUND로 기록했다. 불일치 원문은 자동 수정하지 않았다.

| 기관 | A/B 비교 | 일치 | 불일치 | 일치율 | Cohen kappa |
|---|---:|---:|---:|---:|---:|
| KDI | 49 | 39 | 10 | 0.7959 | 0.5429 |
| BOK | 160 | 68 | 92 | 0.4250 | 0.1359 |
| ALL | 209 | 107 | 102 | 0.5120 | 0.2579 |

A/B 결과의 해석은 `AI_REVIEW_AGREEMENT`로 제한한다. 검수자 신원·독립성 이력이 없으므로 `HUMAN_INTER_RATER_AGREEMENT`로 보고하지 않았다.
BOK의 A/B 불일치와 `B 재검토 대상=Y`는 별도 필드이며 동일한 개념으로 합산하지 않았다.

## 4. 실험 방법

- Keyword-only: 기존 `classify_chunk_by_keywords`의 제목+본문 검색과 가중 후보 점수를 사용한다. 점수는 관련도 확률이 아니며 후보 신호다.
- LLM-only: REUSED_EXECUTED_LLM_PILOT; 관측 결과만 사용하며 신규 API 호출은 0건이다. 미실행 문서는 빈 예측으로 남겼다.
- Hybrid: Keyword 후보만 LLM 입력 대상으로 삼고, 비후보는 명시적 음성으로 남긴다. 후보인데 LLM 결과가 없으면 보류한다.

## 5. 결과 및 평가 상태

- Keyword: 320건 전체 실행, 후보 51건
- LLM: 관측 20건, 신규 호출 0건
- Hybrid: 파일럿·비후보를 합친 관측 결과만 저장; 전체 후보가 채워지지 않아 최종 평가 불가
- 독립 Gold: 0건, 상태 `NOT_READY`; 따라서 최종 Precision/Recall/F1은 산출하지 않았다.
- 아래 proxy 지표는 Excel 명시 라벨 또는 A/B 합의 proxy와의 일치도이며 독립 Gold 성능이 아니다.

| 방법 | 상태 | 전체 모집단 | 예측/관측 수 |
|---|---|---:|---:|
| keyword_only | EXECUTED_OFFLINE | 320 | 320 |
| llm_only | EXECUTED_LLM_PILOT | 320 | 20 |
| hybrid | EXECUTED_LLM_PILOT | 320 | 279 |

## 6. 오분류가 아닌 판정 불일치 분석

Keyword 후보와 reference label이 충돌하는 사례는 11건이며, 독립 Gold가 없으므로 모두 `PENDING_HUMAN_REVIEW`로 기록했다.
대표 유형은 Keyword false positive(키워드가 있으나 reference 0)와 Keyword false negative(키워드가 없으나 reference 2)이다.

## 7. 한계 및 후속 작업

1. 기존 320건 라벨은 개발·예비 분석 자료이며 독립 Gold가 아니다.
2. LLM 파일럿은 20건이고 신규 호출 0건(기록된 API 호출 20건) 범위만 반영한다. 가격 설정이 없어 비용은 확인하지 않았다.
3. KDI/BOK의 원문 표현과 출처 메타데이터가 다르므로 기관별 결과를 전체 성능으로 일반화하지 않는다.
4. Gold Review에서 독립 검수와 합의가 끝난 test set이 준비되면 기존 `compare_precision_methods.py`에 연결해 P/R/F1과 FP/FN 그래프를 생성한다.

## 8. 산출물

- `dataset_counts`: `reports/evaluation/dataset_counts.png`
- `label_distributions`: `reports/evaluation/label_distributions.png`
- `label_confusion_matrix`: `reports/evaluation/label_confusion_matrix.png`
- `label_agreement`: `reports/evaluation/label_agreement.png`
- `method_distributions`: `reports/evaluation/method_distributions.png`
- `method_agreement`: `reports/evaluation/method_agreement.png`
- `api_usage_latency`: `reports/evaluation/api_usage_latency.png`
