# 데이터셋 공통 태그 목록·복수 태그 허용 기준 (초안)

상태: **DRAFT — 사람 결정 필요 항목 포함** · 작성 2026-11-28 · 근거: 로컬 `data/`(git 미포함) 실측

이 문서는 레포 안에 공통 태그 기준 문서가 없어서 만든 초안이다. 현재 데이터와 설정에서
실제로 쓰이는 태그 축만 정리했고, 정해지지 않은 부분은 표시만 하고 임의로 정하지 않았다.

## 1. 현재 실제로 쓰이는 태그 축

| 축 | 값 | 출처 | 실측 |
|---|---|---|---|
| `source_group` | `BOK`, `KDI` | 원본 JSONL, Gold 스키마 | BOK 789건, KDI 2,750건 |
| `chapter_id` | `inflation` (단일) | `configs/chapters.yaml` (`DRAFT_NOT_CANONICAL`) | keyword 후보 148건 모두 `inflation` |
| `matched_keyword_types` | `core`, `alias`, `related`, `opposite` (+ `exclude` 매칭 별도) | `chapters.yaml` `keyword_expansions` | core 133 · related 46 · alias 31 · opposite 4, **복수 유형 51/148행** |
| `relevance_label` / `gold_score` | `0` 없음 · `1` 간접 · `2` 직접 | `configs/independent_gold_schema.json` | AI 제안 365건: 0=241, 1=75, 2=49 (Gold 아님) |
| `conceptCode` | 29개 (C0101~C0107, C0701~C0707, C1101~C1102, C1201~C1207, C1301~C1306) | `data/concept_master.json` | 모두 `reviewedBy/At` null |
| `review_status` | `PENDING`, `PENDING_REVIEW`, `PENDING_INDEPENDENT_REVIEW`, `APPROVED`, `approved` | 여러 산출물 | **대소문자 불일치** 존재 |
| `license_review_status` | Back DB 컬럼(#164) | Back `database/` | AI 데이터 파일에는 없음 |

원본 BOK/KDI 레코드에는 카테고리·태그 필드가 없다(`metadata.related_terms`만 존재).

## 2. 복수 태그 허용 기준 (제안)

| 축 | 복수 허용 | 근거 |
|---|---|---|
| `source_group` | 불가 | 원천 기관은 1개 |
| `chapter_id` | **사람 결정 필요** | 현재 챕터가 1개뿐이라 판단 근거 없음. 제안: 허용하되 챕터별 `gold_score`를 따로 기록 |
| `matched_keyword_types` | 허용 | 후보 생성 신호일 뿐 관련도 아님 (이미 51행이 복수) |
| `gold_score` | 불가 (챕터당 1개) | Gold 스키마 enum 단일값 |
| `conceptCode` (문서↔개념) | 허용 | `concept_sources_reviewed.csv`에서 승인 문서 17개 중 6개가 2개 이상 개념에 연결 |
| `conceptCode` (문항↔개념) | **사람 결정 필요** | 문제 생성·채점은 Back 소유. 제안: 대표 1개 + 보조 0..n |

## 3. 정규화 규칙 (제안)

1. 상태값은 대문자 enum으로 통일: `PENDING_REVIEW`, `PENDING_INDEPENDENT_REVIEW`, `APPROVED`, `REJECTED`.
   AI 설정 `approved_review_status="approved"`(소문자)와 Back 값이 다르면 비교 전에 casefold. **사람 결정 필요**: 기준 표기.
2. 키워드 유형은 `core|alias|related|opposite|exclude` 5개로 고정. `exclude` 매칭은 후보 제외 신호.
3. `chapters.yaml`이 `DRAFT_NOT_CANONICAL`인 동안 `chapter_id` 태그는 평가용이며 서비스 노출 금지.

## 4. 사람 결정 필요 목록

- [ ] 챕터 복수 태그 허용 여부 (멘토/기획)
- [ ] 문항↔개념 대표/보조 태그 구조 (Back 담당과 합의)
- [ ] `review_status` 기준 표기(대문자 enum) 확정 (AI·Back 공동)
- [ ] `chapters.yaml`을 canonical로 승격할지 (멘토 검토)
