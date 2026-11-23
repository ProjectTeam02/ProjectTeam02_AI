# 튜터 모델 비교 실험

`app/model_comparison`은 기존 `MultiTurnRAG`, `ContextBuilder`,
`AnswerGenerator`, OpenRouter `LLMFactory`를 재사용해 동일한 경제·금융 튜터
입력을 5개 모델에 순차 실행하는 실험 하네스입니다.

## 후보 모델과 기능

카탈로그는 2026-11-22에 OpenRouter 모델 페이지에서 확인했습니다.

| 모델 ID | 비교 목적 | 텍스트 | 멀티턴 | 도구/구조화 출력 |
|---|---|---:|---:|---:|
| `google/gemini-3.1-flash-lite` | 저지연·저비용 | 지원 | 지원 | 지원 |
| `google/gemini-3-flash-preview` | 멀티턴·추론 | 지원 | 지원 | 지원 |
| `openai/gpt-5.4-mini` | 설명 정확성 | 지원 | 지원 | 지원 |
| `qwen/qwen3.5-flash-02-23` | 비용 효율 | 지원 | 지원 | 지원 |
| `anthropic/claude-haiku-4.5` | 교육적 설명 품질 | 지원 | 지원 | 지원 |

모든 요청은 OpenRouter의 OpenAI 호환 LLM 경계를 사용하며, 비교 실행에서는
구조화 출력이나 도구 호출을 사용하지 않고 동일한 텍스트 튜터 프롬프트만
사용합니다. 모델의 컨텍스트 길이와 가격은 `app/model_comparison/catalog.py`에
기록되어 있고, 가격으로 계산한 값은 provider가 반환한 토큰 usage가 있을 때만
결과에 저장됩니다.

## 입력 JSONL

한 행은 하나의 검수 시나리오입니다. `corpus`는 모델마다 동일하게 전달되는
승인 근거이며, 데이터셋이 준비되지 않은 상태에서 모델 품질 점수를 만들지 않기
위해 사람이 검수한 자료만 넣습니다.

```json
{
  "case_id": "ECON-001",
  "question": "기준금리가 오르면 대출금리는 어떻게 변할까?",
  "history": [
    {"role": "user", "content": "기준금리가 뭐야?"},
    {"role": "assistant", "content": "기준금리는 ..."}
  ],
  "learning_concept": "기준금리",
  "incorrect_answer": "기준금리가 오르면 대출금리가 항상 내려간다",
  "corpus": [
    {
      "document_id": "BOK-001",
      "chunk_id": "BOK-001:01",
      "source": "bok-reviewed",
      "title": "기준금리",
      "review_status": "approved",
      "content": "검수된 한국은행 설명 ..."
    }
  ],
  "personalized_context": null
}
```

## 실행

기본 실행은 네트워크·API 키를 사용하지 않는 Mock 모드입니다.

```bash
# 100행 빈 템플릿 생성. 기존 파일은 덮어쓰지 않음
.venv/bin/python scripts/compare_tutor_models.py \
  --init-template data/evaluation/tutor_model_cases.jsonl --count 100

# 고정 근거를 채운 뒤 오프라인 경로 확인
.venv/bin/python scripts/compare_tutor_models.py \
  data/evaluation/tutor_model_cases.jsonl \
  --output reports/model_comparison/mock_results.jsonl
```

실제 유료 호출은 명시적으로 `--execute`를 붙인 경우에만 수행됩니다. 키는
환경변수에서만 읽고 결과 JSONL이나 로그에 남기지 않습니다.

```bash
OPENROUTER_API_KEY=... .venv/bin/python scripts/compare_tutor_models.py \
  data/evaluation/tutor_model_cases.jsonl \
  --output reports/model_comparison/live_results.jsonl --execute
```

프로세스가 중단되면 같은 명령을 다시 실행하면 됩니다. 성공(`ok`, `mock`,
`no_evidence`)한 동일 모드의 `(case_id, model_id)` 행은 건너뛰고, 오류 행은
재시도합니다. `--no-resume`를 사용하면 완료 행도 다시 실행합니다.

특정 모델만 소규모로 확인할 수도 있습니다.

```bash
.venv/bin/python scripts/compare_tutor_models.py \
  data/evaluation/tutor_model_cases.jsonl \
  --model openai/gpt-5.4-mini --model qwen/qwen3.5-flash-02-23 \
  --max-cases 5
```

결과 행에는 모델 ID, 모드, 상태, 전체 지연시간, 입력 hash, prompt version,
grounding 상태, 인용 청크, provider usage, reasoning token(제공되는 경우),
계산 가능한 비용, 안전한 오류 유형/코드가 들어갑니다. 원문 프롬프트는
결과에 저장하지 않습니다.

이 실행기는 모델별 응답을 생성하고 운영 로그를 남기는 단계까지 담당합니다.
정확성·grounding·오개념 진단·개인화·교수 전략 점수는 검수된 gold 필드와 별도
평가기를 연결한 뒤 산출해야 하며, 현재 구현은 점수를 임의로 만들지 않습니다.
