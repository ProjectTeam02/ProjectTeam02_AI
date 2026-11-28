# 큐레이션 검수 공백 목록

자동 생성: `scripts/gold_review_kit.py audit-gaps`. 이 문서는 공백을 *나열*만
하며 어떤 항목도 승인하지 않습니다. CSV의 `approve=Y`, `decision=APPROVED`
표시는 DB 승인 이력(검수자·검수일)이 아니므로 공백으로 집계합니다.
행 단위 CSV는 저장소 정책(`reports/**/*.csv` 제외)에 따라
로컬에만 생성됩니다.

## 입력 건수

| 자산 | 건수 |
| --- | ---: |
| 개념 (CONCEPT) | 29 |
| 개념–출처 후보 행 (CONCEPT_SOURCE) | 38 |
|   └ approve=Y 표시 | 25 |
| 선수관계 (PREREQUISITE) | 26 |
| BOK 문서 (BOK_DOCUMENT) | 760 |

## 공백 요약

| 자산 | 공백 행 | 누락 필드별 건수 |
| --- | ---: | --- |
| BOK_DOCUMENT | 760 | reviewed_by 760, reviewed_at 760, license_review_status 760 |
| CONCEPT | 29 | reviewedBy 29, reviewedAt 29, sourceDocumentIds 12 |
| CONCEPT_SOURCE | 38 | reviewed_by 38, reviewed_at 38, license_review_status 38, document_id 11 |
| PREREQUISITE | 26 | reviewed_by 26, reviewed_at 26 |

## 사람이 할 일

- 콘텐츠 검수 담당: 개념 29건의 `reviewed_by`·`reviewed_at` 기록, 근거 문서 없는 개념 연결 결정.
- 데이터 담당: 개념–출처 후보의 검수자·검수일과 `license_review_status`를 DB에 적재 (`database/sql/data/load_concept_source_documents.sql`).
- 데이터 담당: 선수관계 26건의 CSV 결정을 검수자·검수일과 함께 DB에 반영 (`database/sql/data/load_concept_prerequisite_review.sql`).
- 라이선스 승인권자: 한국은행 「경제금융용어 800선」·KDI 용어사전 이용 조건 확인 후 `ai.rag_documents.license_review_status` UPDATE.

## RDS 확인 쿼리

로컬 파일에는 RDS의 실제 승인 이력이 없으므로 최종 확인은 아래 쿼리로 합니다.

```sql
-- RDS에서 실제 승인 이력을 확인할 때 (읽기 전용, ai_user 또는 app_user)
SELECT source_id, review_status, license_review_status,
       (license IS NOT NULL) AS has_license, count(*)
FROM ai.rag_documents GROUP BY 1, 2, 3, 4 ORDER BY 1, 2, 3, 4;
SELECT concept_code, version, status, reviewed_by, reviewed_at
FROM content.concepts WHERE reviewed_by IS NULL OR reviewed_at IS NULL;
```
