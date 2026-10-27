# 멘토 피드백 반영 보고서

기준일: 2026-10-27

## 1. 반영한 방향

- 문제 생성 자료와 Tutor 검색 자료의 사용 흐름을 분리했다.
- 원문 Document와 실제 인덱싱 Chunk를 구분하고, 청크가 없으면 `null`을 유지한다.
- 키워드 기반 후보 선별과 LLM 분류를 분리했다. LLM은 현재 호출하지 않는 dry-run 인터페이스다.
- 자동 후보는 사람 검수 큐로만 제공하고 `APPROVED`로 자동 변경하지 않는다.
- Gold Label이 없으면 정량 평가를 `NOT_EVALUATED`로 남긴다.

## 2. 실제 확인한 데이터와 코드

현재 작업 트리에는 멘토님이 지정한 `data/mentor_dataset/` 3개 파일이 없다. 대신 기존 BOK 789건 파일, BOK loader, DocumentIndexer, Hybrid Retriever, QueryRewriter, MultiTurnRAG, CitationValidator를 읽기 전용으로 확인했다. 외부 수집이나 유료 LLM/Embedding 호출은 하지 않았다.

## 3. 구현 파일

- `app/ingestion/mentor_dataset.py`: 통합 JSONL/커리큘럼 검증, C0704 후보 선별
- `app/evaluation/relevance.py`: 키워드 분류기, LLM dry-run 인터페이스, Gold Label 기반 Precision/Recall/F1
- `scripts/check_knowledge_dataset.py`: terms 파일 검증 CLI
- `scripts/check_curriculum.py`: curriculum 구조 검증 CLI
- `scripts/select_concept_documents.py`: C0704 후보·CSV 검수 큐 생성 CLI
- `app/services/question_generation.py`: 승인 근거가 없으면 차단하고, 있으면 기존 blueprint 기반 `DRAFT_READY` 프롬프트만 준비

## 4. 아직 검증하지 못한 기능

- 3,514건(BOK 760 + KDI 2,754) 실제 파일 검증
- 30 Topic/201 Concept curriculum 정합성 수치 검증
- KDI 문서 후보 및 C0704 승인 매핑
- 사람 100~200개 Gold Label 기반 성능 평가
- 승인 근거 기반 문제 생성
- 실제 OpenRouter LLM/Embedding 호출 및 pgvector 재인덱싱
- 운영 PostgreSQL 현재 적재 상태

## 5. 기존 Multi-turn RAG 상태

기존 `MultiTurnRAG`는 History → Query Rewrite → Retriever → Context → Answer → Citation/Grounding 흐름을 유지한다. 이번 변경은 이 흐름을 재작성하지 않고 C0704 후보/승인 매핑을 별도 입력으로 연결할 수 있는 데이터·평가 계층만 추가했다.

## 6. 실행 명령

```bash
python -m scripts.check_knowledge_dataset
python -m scripts.check_curriculum
python -m scripts.select_concept_documents
pytest -q
```

필수 파일이 없으면 검증 명령은 성공한 것처럼 처리하지 않고 `NOT_AVAILABLE`을 출력한다.

## 7. 다음 단계

1. 멘토 데이터 3개 파일을 로컬 `data/mentor_dataset/`에 전달
2. 두 검증 스크립트로 실제 건수·해시·참조를 확인
3. C0704 후보를 사람이 검수하고 100~200개 Gold Label 작성
4. 승인 문서만 별도 매핑 파일로 확정
5. 승인 근거가 생긴 뒤 문제 생성 draft와 RAG 평가를 별도 실행
