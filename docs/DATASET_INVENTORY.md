# 멘토 피드백 데이터셋 현황

기준일: 2026-10-27

## 확인 결과

요청된 기준 입력 파일은 현재 작업 트리에 존재하지 않는다.

| 파일 | 목적 | 상태 |
|---|---|---|
| `data/mentor_dataset/terms_approved.jsonl` | BOK/KDI 통합 승인 전처리 문서 3,514건 | `NOT_AVAILABLE` |
| `data/mentor_dataset/terms_needs_review.jsonl` | BOK 검토 보류 29건 | `NOT_AVAILABLE` |
| `data/mentor_dataset/curriculum_full.json` | 30 Topic/201 Concept 기준 원본 | `NOT_AVAILABLE` |

파일이 없어 3,514건, BOK 760건, KDI 2,754건, 검토 보류 29건의 일치 여부는 검증하지 않았다. 누락된 파일을 추측하거나 기존 파일을 `terms_approved.jsonl`로 복사하지 않았다.

## 현재 저장소에서 확인된 기존 데이터

| 파일 | 실제 건수 | 용도 | 상태 |
|---|---:|---|---|
| `data/bok_terms_2026.json` | 789 | BOK 원본 구조 검증 | 760 approved / 29 needs_review |
| `data/bok_terms_2026_rag.jsonl` | 789 | 기존 BOK 전용 RAG 입력 | 검토 보류 자동 제외 |
| `data/bok_extraction_report.json` | 1 | 추출 품질 보고서 | 읽기 전용 |

이 BOK 데이터는 멘토 통합 데이터셋의 대체 입력으로 사용하지 않았다. BOK 로더(`app/rag/ingestion/bok_terms_loader.py`)는 RAG ingestion 계층에서 유지된다.

## 현재 로컬 DB 읽기 전용 확인

현재 설정된 로컬 DB `leren`의 `public` 스키마에 읽기 전용으로 접속해 확인한 결과:

| 테이블 | 행 수 |
|---|---:|
| `rag_documents` | 0 |
| `rag_document_chunks` | 0 |
| `rag_index_configurations` | 0 |

따라서 멘토 통합 문서 또는 기존 BOK 문서가 현재 DB에 적재되었다고 판정하지 않았다. 적재·재인덱싱은 수행하지 않았다.

## 코드 감사 요약

- `document_loader.py`: 로컬 manifest 및 텍스트 파일 로더가 구현되어 있다.
- `bok_terms_loader.py`: BOK 원본/RAG ID·해시·검토 플래그 검증과 승인 문서 로딩이 구현되어 있다.
- `DocumentIndexer`: 승인 문서만 LlamaIndex/pgvector에 인덱싱하고 content hash로 중복을 막는다.
- `Retriever`: 기존 BOK exact match와 의미 검색을 병합한다.
- 멘토 통합 JSONL 전용 loader, curriculum validator, C0704 mapping은 이번 변경으로 추가했다.

## 라이선스와 승인

`approved`는 전처리·적재 가능 상태일 뿐 전문가 검수, 교육 적합성, 저작권 허가, 문제 생성 승인 또는 커리큘럼 관련성을 의미하지 않는다. `license` 값은 원문을 수정하지 않고 그대로 보존하며, 이용 허가가 확인되지 않은 값은 승인으로 해석하지 않는다.

## 실행

```bash
python -m scripts.check_knowledge_dataset
python -m scripts.check_curriculum
```

누락 파일은 `NOT_AVAILABLE`로 출력된다. 파일을 전달받은 뒤 동일 명령으로 다시 검증할 수 있다.
