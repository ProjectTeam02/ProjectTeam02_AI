# Data quality report

이 보고서는 원본 Excel·canonical JSON/JSONL을 읽기 전용으로 대조한 결과다.

| 항목 | KDI | BOK | 전체 |
|---|---:|---:|---:|
| 통합 행 | 160 | 160 | 320 |
| 열 수 | 21 | 21 | - |
| 원문 EXACT_MATCH | 160 | 160 | 320 |
| 원문 NORMALIZED_MATCH | 0 | 0 | 0 |
| 원문 CONTENT_MISMATCH | 0 | 0 | 0 |
| source_not_found | 0 | 0 | 0 |
| 숫자형 확정 골드 | 160 | 0 | - |

## 라벨·품질 보류

- KDI `자료 품질=검토필요`: 7건
- BOK `자료 품질=검토필요`: 10건
- BOK `원본 점검플래그` 입력: 10건
- BOK `확정 골드` 비수치 값: {'완료': 160}; 이는 상태값이며 0/1/2로 변환하지 않았다.
- 중복 document_id: 0건; ID 형식 오류: 0건
- 독립 Gold 승인 문서: 0건 (`NOT_READY`)

원문·제목·source locator 불일치는 통합 행에 상태 필드로 보존되며 자동 수정하지 않는다.
