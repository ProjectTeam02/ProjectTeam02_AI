# 튜터 모델 선정 및 운영 전환

## 현재 결정

`scripts/analyze_model_selection.py`는 교육 품질 60점과 운영 효율 40점의
필수 증거 게이트를 모두 통과한 경우에만 기본 모델과 대체 모델을 기록한다.
현재 기록에는 독립 검수 Gold, 실제 Live 비용·TTFT·p50/p95, 완료된 사람 검토,
Context A/B/C 결과가 없으므로 `NOT_READY`이며 운영 모델은 선정하지 않는다.

```bash
.venv/bin/python scripts/analyze_model_selection.py
```

결과는 `reports/model_selection_record.json`과
`reports/model_selection_report.md`에 기록된다. 누락된 수치나 Mock 결과로
운영 모델을 추정하지 않는다.

## 설정 분리

기존 `LLM_PROVIDER`·`LLM_MODEL`은 하위 호환 기본값이다. 최종 승인 뒤에만 다음
환경변수를 별도로 설정한다.

```dotenv
TUTOR_LLM_PROVIDER=openrouter
TUTOR_LLM_MODEL=provider/approved-model
TUTOR_FALLBACK_ENABLED=true
TUTOR_FALLBACK_LLM_PROVIDER=openrouter
TUTOR_FALLBACK_LLM_MODEL=provider/approved-fallback
QUESTION_GENERATION_LLM_PROVIDER=openrouter
QUESTION_GENERATION_LLM_MODEL=provider/question-model
```

튜터 모델은 `TutorService`의 기존 `MultiTurnRAG`에 주입되고, 문제 생성은
별도의 `QuestionGenerationService` 설정을 사용한다. Fallback은 튜터 생성
호출의 실패·Timeout에서만 시도하며, DTO와 내부 API 경로는 바꾸지 않는다.
로그에는 모델 ID와 오류 유형만 남고 프롬프트·응답·키는 남기지 않는다.

## Staging 검증

운영 반영 전 동일한 100건 Gold와 동일 Judge 프롬프트로 모델별 다음을 수집한다.

- 첫 토큰 시간(TTFT), 전체 latency p50/p95
- 성공·Timeout·provider 오류율
- provider usage 기반 실제 비용
- grounding 오류, 경제적 사실 오류, 오개념 오진단
- 완료된 익명 사람 검토와 Context A/B/C 결과

실제 API 실행은 비교/평가 스크립트의 `--execute`를 명시한 staging 환경에서만
수행한다. 현재 저장소의 기본 테스트는 외부 키 없이 Mock으로 실행된다.

## Rollback

1. 배포 전에 기존 `LLM_PROVIDER`·`LLM_MODEL` 값을 별도 보관한다.
2. 장애율, Timeout, grounding 오류가 임계치를 넘으면 `TUTOR_LLM_*`와
   `TUTOR_FALLBACK_*`를 제거해 기존 설정으로 되돌리거나 이전 모델 ID로
   복원한다.
3. 프로세스를 재시작하고 `/health`, 내부 Tutor API 계약 테스트를 확인한다.
4. 설정 변경만으로 복귀할 수 없는 경우 이전 애플리케이션 이미지로 롤백한다.

운영 배포와 실제 유료 호출은 이 저장소에서 자동 실행하지 않으며, 명시적 승인과
staging 결과 확인 후 별도로 수행한다.
