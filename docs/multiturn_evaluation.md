# Multi-turn RAG 평가 실행 가이드

평가 입력은 JSONL만 사용한다. 자동 생성된 사례는 `gold_status=NOT_REVIEWED`로 남기며, 사람이 `REVIEWED`로 바꾸고 `relevant_chunk_ids`, `answerable`, 필요 시 `gold_answer`를 채우기 전에는 Gold로 집계하지 않는다.

## 80건 템플릿

```bash
python scripts/evaluate_multiturn_rag.py --init-template data/multiturn_eval_80.jsonl --count 80
```

각 행은 다음 필드를 사용한다.

```json
{
  "case_id": "MT-001",
  "gold_status": "NOT_REVIEWED",
  "history": [{"role": "user", "content": "기준금리가 뭐야?"}],
  "question": "그게 오르면 대출금리는?",
  "corpus": [{"document_id": "DOC-1", "chunk_id": "DOC-1:1", "content": "..."}],
  "relevant_chunk_ids": [],
  "expected_context_terms": [],
  "answerable": null,
  "gold_answer": null,
  "reviewer_id": null
}
```

## 실행

```bash
python scripts/evaluate_multiturn_rag.py data/multiturn_eval_80.jsonl \
  --output reports/multiturn_rag_offline.json
```

스크립트는 A0 dense, A1 rewrite+dense, A2 rewrite+hybrid, A3 A2+deterministic reranking을 동일 corpus에서 실행한다. 출력에는 Recall@5, nDCG@5, MRR, p50/p95 local latency, multi-turn context accuracy가 포함된다. LLM이 필요한 B0~B3 answer accuracy/faithfulness/hallucination/token/cost는 `NOT_RUN_NO_LLM` 또는 `null`로 남는다. 이는 실제 측정값이 아니다.

실제 provider 비교를 추가할 때도 모델, corpus, top-k, timeout, prompt version, 실행 seed를 고정하고, 같은 reviewed JSONL을 사용해야 한다. API key와 승인 corpus가 없는 상태에서 성능·비용 숫자를 작성하지 않는다.
