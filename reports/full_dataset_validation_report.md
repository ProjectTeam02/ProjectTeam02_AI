# 전체 데이터셋 품질 검증 보고서

## 실행 상태

- 상태: **EXECUTED_LOCAL_READ_ONLY**
- 데이터 버전: `50047d6bd740671252df664aba2ee0bbac845bbf68addbc4f90d6c5efe8e7d0d`
- 문서 단위: **3539건** (`validation['document_count_by_source']`)
- 청크 단위: **3545건** (`validation['chunk_count_by_source']`)
- 후보 집계 단위: `chunk_id + chapter_id`
- 원본 수정: **False**

## 품질 점검 결과

| 점검 항목 | 건수 | 처리 |
|---|---:|---|
| BOK source URL 누락 | 789 | URL을 임의 생성하지 않고 locator 보강 검토 |
| source review 미확정 | 3539 | 운영 승인으로 간주하지 않음 |
| license 미확정 | 3539 | 라이선스 승인 전 사용 차단 |
| 20토큰 미만 | 7 | 삭제하지 않고 검토 큐 유지 |
| 청크 제한 초과 원문 | 6 | token-aware 분할 및 결과 검증 |
| 동일 source 내 content hash 중복 그룹 | 1 | 삭제하지 않고 중복 검토 |

## Lineage 점검

- 문서 ID를 찾지 못한 청크: **0건**
- 중복 Chunk ID: **0건**
- 청크 문서 연결 확인: **True**
- 여러 청크로 분할된 문서: **6건**
- 분할 후 모든 청크가 제한 이하인지: **True**

짧은 문서·중복 문서는 원본에서 삭제하지 않았습니다. BOK의 공식 URL과
라이선스, 문서 품질, 챕터 매핑 승인은 서로 다른 상태로 사람이 확인해야 합니다.
