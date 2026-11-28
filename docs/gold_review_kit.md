# Gold 검수 준비 키트

`scripts/gold_review_kit.py`는 사람 검수를 **준비**하는 도구다. 라벨, 승인 상태,
라이선스 승인 값을 만들거나 바꾸지 않는다. 실제 판정은 기존 도구
(`scripts/gold_review_cli.py`, `scripts/tutor_gold_workflow.py`)로 사람이 입력한다.

원본 데이터는 Git에 없으므로 데이터가 다른 위치에 있으면 `--data-dir`를 준다.

## 현재 상태 (2026-11-28 로컬 데이터 기준)

| 대상 | 파일 | 건수 | 상태 |
| --- | --- | ---: | --- |
| 정밀도 Gold 큐 | `data/labeled/precision/independent_gold_review_queue.csv` | 320 (KDI 160 + BOK 160, test 50) | `PENDING_INDEPENDENT_REVIEW` 320, 승인 0 |
| 튜터 Gold | `data/evaluation/tutor_test_100.jsonl` | 100 (BOK 50, KDI 50) | `PENDING_REVIEW` 100, `conceptCode` 0, `approvedEvidence` 0 |
| 검수 이력 | `gold_review_history.jsonl`, `tutor_gold_review_events.jsonl` | 0 | 파일 없음 |

튜터 100건의 출처 문서는 29개 개념의 근거 문서와 겹치지 않는다(정확 일치 0건,
제목 부분 일치 2건). conceptCode를 붙이려면 사례를 29개 개념 근거에서 다시
뽑을지, 개념 범위를 넓힐지 사람이 먼저 결정해야 한다.

## 명령

```bash
PY=.venv/bin/python

# 1) 이중 검수 배정 시트 (각 건 2명, 검수자 3명 이상이면 쌍을 순환 배정)
$PY scripts/gold_review_kit.py assign --reviewer 검수자1 --reviewer 검수자2 --reviewer 검수자3
#    → reports/gold_review/assignment_sheet.csv (Git 제외)

# 2) 튜터 conceptCode·approvedEvidence 후보 초안 (mappingStatus=DRAFT 고정)
$PY scripts/gold_review_kit.py draft-map
#    → data/evaluation/tutor_concept_evidence_draft.jsonl

# 3) 이중 검수 불일치·Cohen's kappa
$PY scripts/gold_review_kit.py agreement
#    → reports/gold_review/agreement_report.json

# 4) 검수자/검수일/라이선스 공백 목록
$PY scripts/gold_review_kit.py audit-gaps
#    → reports/curation/curation_review_gaps.md (+ 행 단위 CSV, Git 제외)

# 5) 승인 후 Keyword/LLM/Hybrid Precision·Recall·F1 (원커맨드)
$PY scripts/gold_review_kit.py evaluate
#    승인 0건이거나 test split 승인이 끝나지 않았으면 NOT_READY, 종료코드 2
```

`evaluate`는 검수 이력을 큐에 반영한 뒤 `assemble_independent_gold.run`으로
2인 합의·근거 인용·사유 요건을 검사하고, 통과했을 때만
`compare_precision_methods.run`을 실행해
`reports/gold_review/precision_eval_summary.md`에 표를 쓴다.

## 판정 규칙 요약

- 일치도: 검수자 쌍마다 공통 항목의 관측 일치율과 Cohen's kappa. 모든 라벨이
  한 값뿐이라 기대 일치율이 1이면 kappa는 `null`(정의 불가)로 둔다.
- 불일치 항목은 `adjudication_required=true`이며 자동 승인하지 않는다.
- CSV의 `approve=Y`, `decision=APPROVED` 표시는 DB 승인 이력이 아니다.
  검수자·검수일이 기록돼야 공백에서 빠진다.
