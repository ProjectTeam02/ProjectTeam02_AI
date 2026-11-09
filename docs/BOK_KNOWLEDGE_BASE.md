# 한국은행 경제금융용어 800선 Knowledge Base

## 데이터와 출처

- 공식 자료: [한국은행 「경제금융용어 800선」 2026년판](https://www.bok.or.kr/portal/bbs/B0000249/view.do?menuNo=200765&nttId=10096081)
- 공식 PDF SHA-256: `d48f701f84324f734aa2b4fa255d69df2d46bc311e27a16fe50f48041cc9ac9b`
- 용어 레코드: 789개
- 검토 플래그: 29개 (`needs_review`, 인덱싱 제외)
- 현재 인덱싱 가능: 760개 (`approved`)

저장소에는 PDF와 파생 JSON/JSONL을 재배포하지 않는다. 데이터 파일은
검수된 로컬 개발 환경에만 배치하며 `data/*` 규칙으로 Git 추적에서 제외한다.
한국은행 자료의 서비스 이용 허가, 출처 표시 문구, 파생물 배포
범위는 생산 반영 전에 한국은행과 별도로 확인해야 한다. 현재 `license`와
report의 `license_status`는 `permission-and-attribution-review-required`로 유지한다.

## 로컬 파일 구성

다음 파일은 GitHub에 올리지 않고 팀에서 합의한 보안 채널이나
로컬 생성 절차로 `data/`에 준비한다.

- `data/bok_terms_2026.json`: 출처 메타데이터와 789개 원문 기반 레코드
- `data/bok_terms_2026_rag.jsonl`: 용어별 LlamaIndex Document 입력
- `data/bok_extraction_report.json`: 건수, ID, 중복, 검토 대상 검증 결과
- `data/bok_eval_questions.json`: 40개 검색/멀티턴 평가 질문과 gold document ID
- `docs/bok_evaluation_results.json`: 로컬 deterministic embedding 검색 결과

원문 `id`를 `document_id`로 그대로 사용한다. 용어당 하나의 LlamaIndex
`Document`를 만들고, `SentenceSplitter`는 설정된 청크 크기를 넘는 긴 정의만
나눈다. `related_terms`는 Document metadata에 별도로 보존한다.

## 데이터 검증과 인덱싱

PostgreSQL/pgvector를 실행하고 migration을 적용한 다음 실행한다.

```bash
.venv/bin/python -m scripts.ingest_documents \
  --bok-source data/bok_terms_2026.json \
  --bok-terms data/bok_terms_2026_rag.jsonl
```

로더는 두 파일의 레코드 수, ID 순서, 중복, 필수 필드, 본문 해시,
주요 metadata를 대조한다. `review_flags`가 있는 항목이 `approved`이면
즉시 실패하며, 정상 데이터에서도 29개는 인덱싱에서 제외된다.

동일 명령을 재실행하면 `content_hash`로 기존 문서를 감지하여 0개 청크를
추가해야 한다. 정의가 바뀌면 기존 node를 삭제한 뒤 새 node와 metadata를
저장한다.

## 검색 정책

1. JSONL의 공식 표제어, 한글 표제어, 영문·약어를 길이 순으로 정확 일치한다.
2. LlamaIndex `VectorStoreIndex`/`PGVectorStore`로 의미 검색을 수행한다.
3. 정확 일치 결과를 먼저 배치하고 vector 결과를 청크 ID로 중복 제거한다.
4. 상위 문서의 `related_terms`를 최대 `RELATED_TERM_TOP_K`개 정확 검색한다.
5. vector score가 `RETRIEVAL_MIN_SCORE`보다 낮으면 근거로 사용하지 않는다.

BOK 문서는 `knowledge_scope=global`이므로 stage/concept 필터가 있는 운영
요청에서도 검색된다. 기존 stage/concept 전용 문서는 기존 필터를 계속 적용한다.

## 평가 실행

```bash
.venv/bin/python -m scripts.evaluate_bok_rag \
  --questions data/bok_eval_questions.json \
  --output docs/bok_evaluation_results.json
```

임시 PostgreSQL 18.4, pgvector 0.8.6, 128차원 deterministic test embedding으로 실행한
검색 전용 결과는 다음과 같다.

- 40 cases, answerable 36, no-evidence 4
- Recall@5: 1.0
- MRR: 1.0
- Multi-turn context retrieval accuracy: 1.0
- No-evidence accuracy: 1.0
- cold start: 약 1.55 s, warm average: 약 49.9 ms

이 결과는 정확 표제어가 많은 소규모 로컬 평가이며 OpenAI embedding 품질
증거가 아니다. 유료 LLM을 호출하지 않았으므로 citation accuracy,
groundedness, 한국어 답변 품질, provider token/cost는 `null`로 기록했다.

## 멀티턴 확인

다음 세 질문을 동일 `conversationId`로 내부 API에 전송한 로컬 E2E에서
모두 HTTP 200, `grounded=true`, citation `bok800-154`를 반환했다.

1. `기준금리가 뭐야?`
2. `그럼 그게 오르면 어떤 일이 생겨?`
3. `대출금리랑 무슨 관계가 있어?`

이 검증은 로컬 offline-extractive generator와 deterministic embedding을 사용했다.
실제 OpenAI LLM/embedding 호출은 키와 유료 호출 승인이 없어 수행하지 않았다.
