# Keyword-only·LLM-only·Hybrid 비교 실험 계획

## 현재 실행 상태

현재 `라벨링.xlsx`는 160건의 참고 라벨입니다. 확정 골드가 평가자 A 라벨과 동일하고,
평가자 B 입력은 49건뿐이므로 독립 Gold Test Set으로 간주하지 않습니다.

따라서 현재 실행 결과는 다음 상태입니다.

- Keyword-only: 전체 160건에 대한 후보 예측 준비 완료
- LLM-only: `openai/gpt-5.6-sol` 10건 파일럿 결과만 존재
- Hybrid: 확장 키워드 후보 5건에 대한 LLM 결과가 존재하며, 비후보 5건은 누락률 확인용 표본
- 세 방법의 최종 Precision·Recall·F1: 독립 Gold Set 부재로 산출하지 않음
- 문제 생성 자동 승인: 금지, 모든 LLM 결과는 `PENDING`

실행 명령:

```bash
# 독립 Gold Set이 없는 현재 단계: 준비 상태와 비용·커버리지 확인
./.venv/bin/python -m scripts.compare_precision_methods

# 독립 Gold Set 준비 후: 같은 평가셋에서 세 방법을 비교
./.venv/bin/python -m scripts.compare_precision_methods \
  --gold reports/independent_gold_test.csv
```

## 독립 Gold Set 조건

`configs/independent_gold_schema.json`의 필드를 사용합니다. 모든 행은 다음 조건을
만족해야 합니다.

1. `gold_set_status=INDEPENDENT_APPROVED`
2. `review_status=APPROVED`
3. `gold_score`가 0·1·2 중 하나
4. `content_hash`, `source_group`, `split`이 원문과 일치함
5. `review_mode=ADJUDICATED_CONSENSUS`이면 2명 이상, `THIRD_PARTY_REVIEW`이면
   1명 이상의 독립 검수가 확인됨
6. 현재 개발·프롬프트 조정에 사용한 자료와 문서 ID가 겹치지 않음

조건이 하나라도 충족되지 않으면 스크립트는 결과를 `NOT_INDEPENDENT`로 표시하고
성능 수치를 만들지 않습니다.

## 비교 방식

| 방식 | 예측 규칙 | 목적 |
|---|---|---|
| Keyword-only | 확장 키워드 후보 여부 | 외부 API 없는 넓은 후보 기준선 |
| LLM-only | 전체 평가행의 `relevance_score >= threshold` | 의미 기반 단독 분류 |
| Hybrid | 키워드 후보에만 LLM 점수 임계값 적용, 비후보는 명시적 음성 | 비용·재현율 절충 |

임계값은 기본 0.5, 0.6, 0.7, 0.8, 0.9를 비교합니다. 문제 생성은 골드 2점만
양성으로, 튜터 검색은 골드 1·2점을 양성으로 처리합니다.

## 비용·시간·오류 기록

LLM JSONL 결과의 모델명, Provider 응답 모델, 프롬프트 버전, 루브릭 버전, 입력·출력
토큰, 지연시간, 근거 구간 검증 상태를 집계합니다. 설정 파일에 실제 가격이 없으면
비용은 `UNCONFIRMED_CONFIG_REQUIRED`로 남기며 숫자를 추정하지 않습니다.

독립 Gold Set이 준비되면 FP/FN을 `data/labeled/precision/method_failures.csv`에
저장합니다. 오류 원인은 자동으로 확정하지 않고 `PENDING` 상태로 남겨 사람이
`키워드 과다 매칭`, `연관어 누락`, `챕터 경계 모호`, `LLM 판단 오류`, `골드 오류
가능성` 중 하나로 검수합니다.

독립 평가 결과가 준비되고 세 방법 모두 전체 Gold ID를 예측한 경우에만
`reports/method_comparison_metrics.png`에 문제 생성용과 튜터 검색용
Precision·Recall·F1 비교 그래프를 생성합니다. 미예측 행이 있으면
`NOT_EVALUATED_INCOMPLETE_PREDICTIONS`로 남기고 그래프도 생성하지 않습니다.
