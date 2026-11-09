# STEP 3-A Gold Label 검수 가이드

## 1. 검수 목적

인플레이션 파일럿의 Keyword-only 예측을 사람이 검증할 수 있는 Gold Label 데이터로 변환하기 위한 가이드다. 자동 예측은 정답이 아니며, `gold_label`은 반드시 사람이 입력한다.

검수 범위는 다음 세 집합이다.

| 집합 | 건수 | 선정 방식 |
|---|---:|---|
| Keyword 후보 | 55 | 기존 `keyword-v1`이 선택한 전체 후보 |
| 경계 사례 | 50 | Keyword 미선택 734건 중 경제 맥락 키워드 점수 상위 50건 |
| 무작위 표본 | 100 | 경계 사례를 제외한 나머지에서 seed 20261029로 추출 |
| 합계 | 205 | 중복 없는 검수 큐 |

전체 모집단은 BOK RAG 789건이다. 원본 JSONL은 수정하지 않는다.

## 2. 식별자 및 curriculum 상태

로컬에서 확인한 실제 curriculum JSON은 없다. `docs/CURRICULUM_MAPPING_DESIGN.md`에는 `C0704`, `R07_S04`, `C0701`, `C0703`이 설계·테스트 참조로 등장하지만, 운영 curriculum 파일에서 검증된 canonical ID는 아니다.

따라서 검수 시 다음 칸을 임의로 채우지 않는다.

- `chapter_id`
- `concept_id`
- `concept_code`
- `stage_id`

현재 파일럿의 `pilot_chapter_label=인플레이션`은 사람이 이해하기 위한 설계 라벨이다.

## 3. 검수 시트

- [`candidate_review_sheet.csv`](candidate_review_sheet.csv): 55개 Keyword 후보
- [`boundary_review_sheet.csv`](boundary_review_sheet.csv): 50개 경계 사례
- [`random_review_sheet.csv`](random_review_sheet.csv): 100개 무작위 표본
- [`gold_label_template.csv`](gold_label_template.csv): 위 205개를 합친 평가용 Gold Label 입력 파일
- [`full_corpus_gold_template.csv`](full_corpus_gold_template.csv): 정확한 전체 모집단 평가를 위한 789개 템플릿

각 행은 `document_id` 기준이다. 원문 전체를 복사하지 않고 `evidence_sentence`, `source_url`, `printed_page`, `content_hash`로 검증 가능하게 했다.

## 4. Gold Label 입력 기준

`gold_label`에는 다음 세 값만 입력한다.

| 값 | 기준 |
|---|---|
| `approved` | 인플레이션 학습목표와 직접 연결되고, 근거 문장이 충분하며, 사람이 관련성을 확인함 |
| `needs_review` | 키워드나 맥락은 있으나 챕터 범위·근거·출처를 추가 확인해야 함 |
| `irrelevant` | 단순 문자열 포함, 법률명·사례명·부수적 언급 등으로 인플레이션 학습자료로 보기 어려움 |

주의사항:

1. Keyword `DIRECT` 또는 `INDIRECT`를 `approved`로 복사하지 않는다.
2. Keyword `EXCLUDE`를 자동으로 `irrelevant`로 확정하지 않는다.
3. `needs_review`는 negative가 아니다. 평가 시 보류로 제외한다.
4. `source_review_status=needs_review`인 자료는 인플레이션 관련성이 있어 보여도 최종 운영 승인으로 처리하지 않는다.
5. `license_status`가 `approved`가 아니면 Gold Label과 별개로 운영 사용을 허용하지 않는다.
6. `review_note`에 판단 근거를 적고, `reviewer`, `reviewed_at`을 남긴다.

## 5. 추천 검수 절차

1. `source_url`, `printed_page`, `content_hash`를 확인한다.
2. `evidence_sentence`가 실제 원문을 대표하는지 확인한다.
3. 인플레이션 학습목표와 직접 연결되는지 판단한다.
4. `gold_label`을 입력한다.
5. `approved` 또는 `irrelevant`에는 근거를 기록한다.
6. 두 reviewer의 판단이 다르면 adjudicator가 최종 결정을 기록한다.

최소한 55개 후보는 전부 검수한다. 파일럿 metric을 얻으려면 205개 검수 큐 전체에 라벨을 입력해야 한다. 205개 표본 결과는 표본 성능이며, 789개 전체의 정확한 recall로 보고하지 않는다.
