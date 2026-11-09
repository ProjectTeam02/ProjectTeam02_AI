# STEP 3-A 분류 실험 평가 계획

## 1. 현재 실행 상태

Keyword-only baseline을 BOK RAG 789건 전체에 실행했다.

| 항목 | 결과 |
|---|---:|
| 전체 문서 | 789 |
| Keyword 매칭 후보 | 55 |
| `DIRECT` | 41 |
| `INDIRECT` | 13 |
| 명시적 `EXCLUDE` 후보 | 1 |
| Gold Label 입력 | 0/205 |
| 현재 평가 상태 | `NOT_EVALUATED` |

전체 예측은 [`keyword_predictions.csv`](keyword_predictions.csv), 실행 상태는 [`evaluation_result.json`](evaluation_result.json)에 저장된다.

## 2. 표본 추출

상세 값은 [`sampling_manifest.json`](sampling_manifest.json)에 기록되어 있다.

- 모집단: `data/bok_terms_2026_rag.jsonl` 789건
- Keyword 선택: 55건
- Keyword 미선택: 734건
- 경계 사례: 미선택 734건에서 관련 경제 맥락 용어 점수 상위 50건
- 무작위 표본: 경계 50건을 제외한 나머지에서 `random.Random(20261029).sample(sorted(document_ids), 100)`
- 중복 방지: document ID 기준으로 경계 사례와 무작위 표본을 분리
- 전체 검수 큐: 205건

표본 기반 결과는 `general_population_recall_allowed=false`로 기록한다. 789건 전체 recall을 정확히 산출하려면 `full_corpus_gold_template.csv`의 789개 행을 모두 사람이 라벨링해야 한다.

## 3. 평가 입력과 상태

평가 스크립트:

```bash
./.venv/bin/python -m scripts.evaluate_step3_gold
```

기본 입력은 다음과 같다.

- predictions: `reports/step3/keyword_predictions.csv`
- gold: `reports/step3/gold_label_template.csv`
- scope: `sampled_review_set`
- output: `reports/step3/evaluation_result.json`

전체 모집단 평가를 수행할 때:

```bash
./.venv/bin/python -m scripts.evaluate_step3_gold \
  --gold reports/step3/full_corpus_gold_template.csv \
  --scope full_corpus \
  --output reports/step3/full_corpus_evaluation_result.json
```

Gold Label이 비어 있거나 일부만 채워졌으면 `NOT_EVALUATED`다. 자동 예측은 누락된 Gold Label을 채우는 데 사용하지 않는다.

## 4. Metric 정의

이진 relevance 평가는 `approved`를 positive로 하고 `irrelevant`를 negative로 한다. `needs_review`는 어느 쪽에도 넣지 않고 보류한다.

```text
Precision = TP / (TP + FP)
Recall    = TP / (TP + FN)
F1        = 2 * Precision * Recall / (Precision + Recall)
```

평가 결과에는 다음을 함께 기록한다.

- `labeled_count`
- `deferred_needs_review_count`
- `resolved_count_for_binary_metrics`
- `missing_gold_count`
- `general_population_recall_allowed`
- `needs_review_policy`

검수 큐에서 `approved`와 `irrelevant`가 모두 존재해야 binary metric을 계산한다. `needs_review`만 있는 경우에도 `NOT_EVALUATED`다.

## 5. Enum 감사 결과

현재 코드와 STEP 2 정책에는 다음 값들이 공존한다.

| 계층 | 현재 값 | 의미 |
|---|---|---|
| source review | `approved`, `needs_review` | 기존 ingestion/index eligibility |
| keyword output | `DIRECT`, `INDIRECT`, `EXCLUDE` | 자동 분류 출력 |
| candidate workflow | `PENDING` | 사람 검수 전 상태 |
| proposed mapping review | `approved`, `needs_review`, `irrelevant` | 사람이 chapter/concept relevance를 판정 |
| license | raw `license` 문자열 | 권한 상태와 별도 정규화 필요 |

`PENDING`은 Gold Label이 아니며, `DIRECT`도 승인 라벨이 아니다. 다음 구현 단계에서 `mapping_review_status`를 Gold Label enum과 동일한 소문자 값으로 통일하는 것을 권장한다. `source_review_status`와 `license_status`는 별도 필드로 유지한다.

## 6. 문서-청크-Embedding 설계

상세 설계는 [`chunk_embedding_design.json`](chunk_embedding_design.json)에 있다.

현재 구현:

- 원본 1건은 LlamaIndex `Document` 1건으로 변환
- `SentenceSplitter(chunk_size=700, chunk_overlap=100)` 적용
- `chunk_id = document_id:sha256(content)[:12]:chunk_index`
- PostgreSQL `rag_documents`와 `rag_document_chunks`에 문서·청크 metadata를 저장하는 코드가 있음
- 실제 vector owner는 LlamaIndex `PGVectorStore`
- `RAGChunk.embedding`은 application audit table에서 `None`이며 vector는 PGVectorStore가 소유
- 문서 `content_hash`는 `RAGDocument`에서 unique로 관리

제안 embedding cache key:

```text
sha256(
  embedding_provider |
  embedding_model |
  embedding_dimension |
  document_version |
  document_content_hash |
  chunk_size |
  chunk_overlap |
  chunk_id |
  chunk_content_hash
)
```

모델·버전·본문·chunk 설정·chunk 내용 중 하나라도 바뀌면 cache miss가 되어야 한다. `chunk_content_hash`는 현재 DB schema에 추가하지 않았으며, 본 문서에서는 설계안으로만 기록한다.

## 7. 방법별 실험 순서

1. Keyword-only: 현재 `keyword-v1`을 baseline으로 평가
2. 사람 검수: 55 후보 + 50 경계 + 100 무작위 표본 라벨링
3. LLM-only: 외부 호출 승인 후 동일 Gold Set에 적용
4. Hybrid: high-recall keyword 후보 중 애매한 행만 LLM 검토
5. 동일 test Gold Set에서 Precision/Recall/F1 비교

LLM-only와 Hybrid는 이번 단계에서 호출하지 않는다. 모든 방법은 동일한 document ID, 동일한 Gold Label, 동일한 evidence 검증 규칙을 사용해야 한다.
