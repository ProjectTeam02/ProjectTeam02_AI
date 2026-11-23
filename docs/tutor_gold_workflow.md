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

## 독립 검수

검수자는 `data/evaluation/tutor_gold_review_queue.jsonl` 또는 기존의
append-only Gold 검수 도구를 사용해 정답, 근거, 오개념 유형, 교수 행동, source와
license 상태를 확인합니다. 두 명 이상의 합의 검수 또는 정의된 제3자 검수
이력이 있어야 하며, 완료 전에는 `INDEPENDENT_APPROVED`로 바꾸지 않습니다.

## 최종 모델 비교와 Smoke Test

```bash
# Gold와 무관한 실제 OpenRouter 연결 확인
OPENROUTER_API_KEY=... .venv/bin/python scripts/openrouter_smoke_test.py

# 승인 후에만 최종 모델 비교
OPENROUTER_API_KEY=... .venv/bin/python scripts/compare_tutor_models.py \
  data/evaluation/tutor_test_100.jsonl --execute \
  --output data/evaluation/tutor_model_results_live.jsonl
```

최종 비교는 Gold validator가 차단하면 실행되지 않습니다. Smoke Test는 응답
원문을 저장하지 않고 비용·latency·usage와 PASS 여부만 기록합니다.
