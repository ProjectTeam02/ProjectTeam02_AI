# Tutor Gold 완성 워크플로

## 현재 입력 확인

현재 브랜치에는 `data/evaluation/tutor_test_100.jsonl`이 있으나,
`tutor_test_100_kdi_candidates.jsonl`, `configs/model_candidates.json`,
`scripts/validate_tutor_gold.py`는 원래 존재하지 않았습니다. 모델 후보의
canonical source는 `app/model_comparison/catalog.py`이며, Gold 검증기는 이번
작업에서 추가되었습니다.

현재 100건은 KDI/BOK 원문 후보와 콘텐츠 해시는 보유하지만 다음은 승인되지
않았습니다.

- `conceptCode`: 100건 누락
- `approvedEvidence`: 0건
- source review/license: 미확정
- `goldStatus`: 100건 `PENDING_REVIEW`
- 독립 사람 검수: 미완료

`data/curation/2026-11-23/`의 12개 구조화 파일이 canonical 입력입니다. 현재
구조화 디렉터리가 없고 `data/` 루트의 동일 이름 flat export만 있으면 검증기는
이를 확인용 레거시 레이아웃으로 표시하고 전체 curation 상태를 `BLOCKED`로
유지합니다. flat CSV의 `APPROVED`/`Y` 표시는 DB 승인 이력이나 라이선스 승인으로
승격하지 않습니다.

## 검증 실행

```bash
.venv/bin/python scripts/validate_tutor_gold.py --report-only
```

출력:

- `reports/evaluation/tutor_gold_validation_report.md`
- `reports/evaluation/tutor_gold_validation.json`
- `data/evaluation/tutor_gold_review_queue.jsonl` (Git 제외 로컬 큐)

`answerDraft`는 승인 전 사람이 검토할 초안일 뿐이며 Gold 승인으로 취급하지
않습니다. Backend의 실제 개념 코드 파일이 준비되면 다음처럼 명시적으로
제공합니다.

```bash
.venv/bin/python scripts/validate_tutor_gold.py \
  --concept-map /path/to/backend_concept_map.json
```

개념 코드 파일은 `sourceId` 또는 `documentId`와 `conceptCode`를 포함하는 JSON
객체 또는 목록이어야 합니다. 확인할 수 없는 코드는 자동 생성하지 않습니다.

## 튜터 100건 검수 진행 워크플로우

튜터 사례는 기존 원본 JSONL을 수정하지 않고 별도 append-only 이벤트로 검수
진행을 기록합니다. 기본 단계는 `REVIEW_IN_PROGRESS`이며, 승인 사례가 일부
축적되면 `INTERIM_MODEL_COMPARISON`, 100건 전체가 승인되면
`FINAL_MODEL_EVALUATION`으로 보고합니다.

```bash
# 100건의 사례·근거·개념 매핑 확인 큐 생성
.venv/bin/python scripts/tutor_gold_workflow.py --prepare

# 사람 검수 이벤트 기록 예시(승인 처리가 아님)
.venv/bin/python scripts/tutor_gold_workflow.py --record-review \
  --case-id TUTOR-001 --reviewer-id reviewer-a \
  --status IN_REVIEW --decision IN_REVIEW \
  --notes "개념과 원문 근거 확인 중"

# 독립 검수·합의가 끝난 사례만 별도 Interim 입력으로 추출
.venv/bin/python scripts/tutor_gold_workflow.py --extract-interim
```

`APPROVE` 이벤트는 canonical conceptCode, 승인된 출처·라이선스, 원문과
일치하는 evidence가 있어야 저장됩니다. Interim 추출은 서로 다른 두 검수자의
승인 이벤트와 adjudication 이벤트가 모두 있을 때만 수행하며, 원본 Gold 행을
변경하거나 검수 결과를 추론하지 않습니다.

## 독립 검수

검수자는 `data/evaluation/tutor_gold_review_queue.jsonl` 또는 기존의
append-only Gold 검수 도구를 사용해 정답, 근거, 오개념 유형, 교수 행동, source와
license 상태를 확인합니다. 두 명 이상의 합의 검수 또는 정의된 제3자 검수
이력이 있어야 하며, 완료 전에는 `INDEPENDENT_APPROVED`로 바꾸지 않습니다.

## 최종 모델 비교와 Smoke Test

```bash
# Gold와 무관한 catalog-only dry-run (기본값)
.venv/bin/python scripts/openrouter_smoke_test.py

# Gold와 무관한 실제 OpenRouter 연결 확인이 명시적으로 필요한 경우
OPENROUTER_API_KEY=... .venv/bin/python scripts/openrouter_smoke_test.py --execute

# 비용 없는 실행기·RAG 경로 검증
.venv/bin/python scripts/compare_tutor_models.py \
  data/evaluation/tutor_test_100.jsonl --stage mock \
  --output /tmp/tutor-mock.jsonl

# 별도 adjudication으로 추출한 일부 사례만 Interim 비교
OPENROUTER_API_KEY=... .venv/bin/python scripts/compare_tutor_models.py \
  data/evaluation/tutor_interim_approved.jsonl \
  --stage interim --execute --max-cost-usd 1.0

# 승인 후에만 최종 모델 비교
OPENROUTER_API_KEY=... .venv/bin/python scripts/compare_tutor_models.py \
  data/evaluation/tutor_test_100_approved.jsonl --stage final --execute \
  --output data/evaluation/tutor_model_results_live.jsonl
```

최종 비교는 Gold validator가 차단하면 실행되지 않습니다. Smoke Test는 응답
원문을 저장하지 않고 비용·latency·usage와 PASS 여부만 기록합니다.
Interim 품질 결과는 `SCORED_PRELIMINARY`로 기록하며 최종 모델 선정 게이트에
사용하지 않습니다. Final 비교는 100건 전체가 독립 승인된 경우에만 실행됩니다.

## 개인화 Context A/B/C 비교

동일 사례를 다음 세 변형으로 확장해 별도 결과 파일에 기록할 수 있습니다.

- A: 질문 + 현재 개념
- B: A + 이전 대화
- C: B + Backend 학습 프로필·승인된 선수 개념 Context

```bash
.venv/bin/python scripts/compare_tutor_contexts.py \
  data/evaluation/tutor_test_100.jsonl --stage mock --max-cases 1 \
  --output /tmp/tutor-context-mock.jsonl
```

Context 비교 결과는 모델 비교 결과와 섞지 않으며, 실제 승인된 Gold가 없는
경우 Mock 결과는 기능 검증용으로만 남습니다. 품질 하네스는
`::context-A/B/C` 사례 ID를 원본 사례에 연결하되, Gold 승인 게이트를 그대로
적용합니다.
