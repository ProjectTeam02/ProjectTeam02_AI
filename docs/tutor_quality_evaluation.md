# Tutor 교육 품질 60점 평가

`app/evaluation/tutor_quality.py`는 모델 비교 결과를 동일한 Judge 프롬프트로
평가한다. 기본 실행은 Mock Judge이며, `--execute`를 명시한 경우에만
OpenRouter를 호출한다.

## Rubric

| 항목 | 배점 | 채점 기준 |
|---|---:|---|
| 경제적 정확성 | 15 | 개념·조건·수치·인과관계가 승인 자료와 경제적 사실에 맞음 |
| RAG Grounding | 10 | 승인 근거 사용, 실제 원문 인용, 유효한 문서/청크 식별자 |
| 오개념 진단·교정 | 15 | 오개념을 성급히 확정하지 않고 확인 질문과 근거 기반 교정 제공 |
| 개인화·멀티턴 | 10 | 학습자 신호와 이전 맥락 유지, 과도한 진단·개인정보 노출 방지 |
| 교수 전략·이해도 확인 | 10 | 쉬운 설명, 단계적 안내, 예시와 이해도 확인 제공 |

세부 점수는 다음 공통 구간을 기준으로 0점부터 최대점까지 연속적으로 부여한다.

| 구간 | 기준 |
|---|---|
| 0점 | 핵심 오류·무근거 인용·오진단·맥락 무시·개인정보 노출 등으로 교육적으로 사용할 수 없음 |
| 부분점수 | 핵심 방향은 맞지만 조건·근거·개인화·교수 전략 중 일부가 누락되거나 부정확함 |
| 최대점 | 해당 항목의 핵심 기준과 예외·한계를 충족하고 독립 검토 가능한 수준임 |

각 항목의 구체적인 0/부분/최대점 문구는
`app/evaluation/tutor_quality.py`의 `RUBRIC`에 버전 관리한다.

각 차원은 0점부터 최대 배점까지 Judge가 채점한다. 총점은 차원 합계에서
검출된 감점을 뺀 뒤 0~60점으로 제한한다. 경제적 사실 오류는 답변이 유창해도
정확성 감점과 중대 오류로 기록한다.

## 실행

```bash
# 앞 단계의 100건 모델 비교 결과를 사용한 오프라인 평가
.venv/bin/python scripts/evaluate_tutor_quality.py --force

# 실제 Judge 호출은 명시적으로만 활성화
OPENROUTER_API_KEY=... .venv/bin/python scripts/evaluate_tutor_quality.py \
  --execute --judge-model openai/gpt-5.4-mini --force
```

결과는 다음 파일에 저장된다.

- `data/evaluation/tutor_quality_results.jsonl`: 자동 Judge 결과
- `data/evaluation/tutor_human_review_anonymous.jsonl`: 모델 ID를 제거한 사람 검토 큐
- `reports/evaluation/tutor_quality_deduction_report.md`: 감점·중대 오류 집계
- `reports/evaluation/tutor_quality_schema.json`: 결과 JSON Schema

`goldStatus=INDEPENDENT_APPROVED`, canonical `conceptCode`, 승인된 근거가 모두
없는 사례는 `NOT_EVALUATED_UNREVIEWED_GOLD`로 저장하며 점수는 `null`이다.
Judge가 반환한 `documentId/chunkId/quote`는 승인 원문의 실제 문자열과 대조한다.

자동 결과는 `evaluationSource=AUTOMATED_LLM_JUDGE`, 사람 검토 결과는 별도 파일의
`evaluationSource=HUMAN_REVIEW_PENDING`으로 분리한다. Judge 입력에는 평가 대상
모델 ID를 포함하지 않으며, `judgeModelId`와 `judgePromptVersion`만 결과에 남긴다.
