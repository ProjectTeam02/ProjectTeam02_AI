# Leren 실행 하네스

## Stage contracts

| Stage | Input | Output | Failure policy |
|---|---|---|---|
| Conversation Context | Node history/summary, bounded by count/token policy | bounded history + `historyFromSeq` | reject malformed sequence; never duplicate summary-covered turns |
| Query Rewriting | current question + bounded history | standalone search query | call only for context-dependent follow-up; timeout/failure uses deterministic fallback |
| Retrieval | rewritten query + concept/stage/scope | approved `RetrievedDocument[]` | sparse failure falls back to dense; no approved evidence means safe hold |
| Reranking | retrieved documents | ordered documents | optional deterministic reranker; no new model dependency by default |
| Evidence Check | answer markers + retrieved IDs | citation identity/overlap result | unknown citation is discarded; unsupported answer is held |
| Answer Generation | original question + separated history/evidence context | answer text | bounded timeout/retry; provider failure returns API error, not a fabricated answer |
| Groundedness Validation | answer + evidence | grounded/insufficient | insufficient evidence is returned as a safe hold response |

`ExecutionHarness` enforces a finite timeout and `rag_max_retries`; each event
records only stage, status, attempt, latency, and exception type. It does not
log user content or credentials. `TutorService` returns provider-reported token
usage and computes cost only when both input/output price settings are
explicitly configured. Otherwise cost is `null`, not guessed.

## Development harness

The repository knowledge map is `AGENTS.md`; architecture and API contracts are
the deeper sources of truth. Run the existing full suite before changing a
contract. New retrieval experiments belong in
`scripts/evaluate_multiturn_rag.py` and use the same JSONL labels across arms
A0-A3. B0-B3 generation metrics require a configured model and reviewed Gold;
the offline runner intentionally reports them as unavailable.

## QG/QV boundary

`QuestionGenerationService` first searches approved evidence, generates a batch,
validates schema/source IDs/choice uniqueness, and independently validates each
item. `REVISE` is bounded by `QUESTION_MAX_REVISION_ATTEMPTS`; `REJECT` or
exhaustion fails the batch with a reason. The FastAPI endpoint is internal and
returns a validated draft only. Node.js/admin persistence, review status, and
publication remain outside this repository's public learner API.
