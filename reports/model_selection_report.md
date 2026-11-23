# 최종 튜터 모델 선정 보고서

- 결정 상태: `NOT_READY`
- 최종 기본 모델: 선정하지 않음
- 최종 대체 모델: 선정하지 않음
- 정책: 교육 품질 60점 + 운영 효율 40점

## 모델별 실험 기록

| 모델 | 비교 건수 | Live 성공 | 교육 점수 건수 | 실제 비용(USD) | TTFT | p50/p95(ms) |
|---|---:|---:|---:|---:|---|---|
| `google/gemini-3.1-flash-lite` | 100 | 0 | 0 | N/A | N/A | N/A/N/A |
| `google/gemini-3-flash-preview` | 100 | 0 | 0 | N/A | N/A | N/A/N/A |
| `openai/gpt-5.4-mini` | 100 | 0 | 0 | N/A | N/A | N/A/N/A |
| `qwen/qwen3.5-flash-02-23` | 100 | 0 | 0 | N/A | N/A | N/A/N/A |
| `anthropic/claude-haiku-4.5` | 100 | 0 | 0 | N/A | N/A | N/A/N/A |

## 선정 게이트

- independentGold: `BLOCKED`
- educationScores: `BLOCKED`
- liveOperations: `BLOCKED`
- humanReview: `BLOCKED`
- contextABC: `BLOCKED`

## 미완료 근거

- 100개 사례의 INDEPENDENT_APPROVED Gold
- 5개 모델 모두의 검수 Gold 기반 교육 품질 점수
- 5개 모델의 실제 live 비용·TTFT·p50/p95·성공률
- 완료 상태의 익명 사람 검토 결과
- 개인화 Context A/B/C 실험 결과
- Context A/B/C 결과 JSONL

이 보고서의 `NOT_READY` 상태에서는 모델 ID를 운영 설정에 승격하지 않는다.
실제 Staging 호출과 배포는 명시적 승인 후 별도 실행한다.
