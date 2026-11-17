# Leren AI repository map

This file is the short agent/developer map. The detailed source of truth is in
`docs/architecture.md`, `docs/TUTOR_INTERNAL_API_CONTRACT.md`,
`docs/rag_pipeline.md`, and `docs/multiturn_evaluation.md`.

## Boundaries

- `main.py` imports the FastAPI app from `app/main.py`.
- Node.js owns the internal conversation/request persistence and calls
  `POST /internal/v1/tutor/answer` with the camelCase contract.
- `/api/tutor/chat` is a legacy snake_case compatibility route using the
  process-local history repository.
- FastAPI owns RAG document metadata/vector indexing and `ai_user_memories`.
- Only `review_status=approved` evidence may enter retrieval or QG/QV.

## Runtime flow

`Conversation Context -> Query Rewriting -> Retrieval -> Reranking -> Evidence
Check -> Answer Generation -> Groundedness Validation -> Response`.

The implementation is split across `app/rag/memory`, `app/rag/retrieval`,
`app/rag/harness.py`, `app/rag/generation`, and `app/rag/grounding`. The
PostgreSQL sparse adapter is optional and reuses existing RAG tables; it does
not introduce a search service or schema migration.

## Change rules

- Keep existing paths, DTO aliases, response status values, and database
  ownership boundaries compatible.
- Do not log questions, conversation content, tokens, or secrets. Stage logs
  may contain only stage, status, attempt, latency, and safe exception type.
- Do not treat generated evaluation labels as Gold. Use JSONL and explicit
  `gold_status=REVIEWED`; do not add CSV artifacts.
- Do not copy research code/data when its repository license is not verified.
- QG output is an internal validated draft. Backend/admin review owns
  persistence and publication; never expose an unreviewed item to learners.

## Verification

```bash
python -m pytest -q
python -m ruff check app tests scripts/evaluate_multiturn_rag.py
python scripts/evaluate_multiturn_rag.py --init-template /tmp/leren_multiturn_eval.jsonl --count 80
```

If provider credentials or PostgreSQL are unavailable, run the unit/contract
suite and the offline evaluator. Report external LLM/pgvector metrics as not
run; do not estimate them from local fixtures.
