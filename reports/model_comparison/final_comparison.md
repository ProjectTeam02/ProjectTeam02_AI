# Leren Tutor 모델 비교 결과

- 평가 상태: `NOT_READY`
- 생성 시각: `2026-11-24T07:01:12.606315+00:00`
- 교육 품질과 운영 효율 점수는 필수 증거가 없어 산출하지 않음
- 실제 측정하지 않은 값은 `N/A`로 표시

## 최종 비교표

| 모델 | 교육 품질 /60 | 운영 효율 /40 | 총점 /100 | p95(ms) | 평균 실제 비용(USD) | 중대 오류율 | 상태 |
|---|---:|---:|---:|---:|---:|---:|---|
| `google/gemini-3.1-flash-lite` | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_NOT_READY |
| `google/gemini-3-flash-preview` | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_NOT_READY |
| `openai/gpt-5.4-mini` | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_NOT_READY |
| `qwen/qwen3.5-flash-02-23` | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_NOT_READY |
| `anthropic/claude-haiku-4.5` | N/A | N/A | N/A | N/A | N/A | N/A | BLOCKED_NOT_READY |

## 모델 카탈로그 확인

가격은 OpenRouter 카탈로그 조회 시점 기준 USD/1M tokens이며, 실제 호출 비용과 다르다.

| 모델 | 사용 가능 | 입력 가격 | 출력 가격 | Context | 구조화 출력 |
|---|---|---:|---:|---:|---|
| `google/gemini-3.1-flash-lite` | True | 0.25 | 1.5 | 1048576 | True |
| `google/gemini-3-flash-preview` | True | 0.5 | 3.0 | 1048576 | True |
| `openai/gpt-5.4-mini` | True | 0.75 | 4.5 | 400000 | True |
| `qwen/qwen3.5-flash-02-23` | True | 0.065 | 0.26 | 1000000 | True |
| `anthropic/claude-haiku-4.5` | True | 1.0 | 5.0 | 200000 | True |

## 해석

현재 100개 Gold 사례가 독립 승인되지 않았고 실제 Live 호출도 수행하지 않았으므로 모델 순위와 기본/Fallback 모델을 선정하지 않는다.
Mock 결과는 하네스 동작 검증용이며 교육 품질 점수에 포함하지 않는다.
