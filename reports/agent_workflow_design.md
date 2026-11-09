# Leren 에이전트 워크플로우 설계

이번 단계에서는 아래 흐름을 문서로만 설계했다. FastAPI API, Node.js 연동,
실제 문제 생성 호출과 에이전트 실행은 구현하지 않았다.

## A. 문제 생성

```text
승인된 청크 조회
  → 챕터·학습목표·blueprint 확인
  → 근거 청크를 LLM에 직접 제공
  → 문제·보기·정답·해설 생성
  → JSON schema / 정답 유일성 / 근거 중첩 / 중복 검증
  → Human Review
  → 문제은행 draft 또는 게시 승인
```

| 단계 | 담당 | 입력 | 출력 |
|---|---|---|---|
| 자료 선택 | Python + PostgreSQL | chunk sidecar, approval policy | approved evidence set |
| 프롬프트 조립 | FastAPI | chapter, blueprint, evidence | generation request |
| 생성 | LLM | prompt | question draft |
| 자동검증 | FastAPI/Python | draft, evidence | validation result |
| 사람 검수 | Human Reviewer | draft, evidence, flags | APPROVED/REJECTED/NEEDS_REVISION |
| 저장·게시 | Node.js + 문제은행 DB | reviewed draft | product question |

문제 생성 입력은 `evidence_chunk_id`, `evidence_quote`, `source_url/source_locator`,
`content_hash`, `chapter_id`, `rubric_version`을 포함한다. FastAPI는 AI 생성·검증을
담당하고, Node.js는 인증·게시 상태·사용자 노출·채점 흐름을 담당한다.

## B. AI Tutor Multi-turn RAG

```text
사용자 질문
  → Node.js가 FastAPI 호출
  → 대화 이력 조회 및 query rewriting
  → pgvector + exact/hybrid retrieval
  → citation/grounding 품질 확인
  → LLM 답변 생성
  → 출처 포함 응답
  → 대화·메시지 저장
```

| 단계 | 담당 | 입력 | 출력 |
|---|---|---|---|
| 요청·인증 | Node.js | user/session/question | internal tutor request |
| 맥락 구성 | FastAPI | history, memory, question | bounded context |
| 재작성 | LlamaIndex/FastAPI LLM | conversation context | standalone query |
| 검색 | LlamaIndex + PostgreSQL/pgvector | query, policy | ranked chunks |
| 근거 확인 | FastAPI | chunks, query | grounding/citation flags |
| 답변 생성 | LLM | query, history, evidence | answer + citations |
| 저장 | Node.js / 협의된 repository | request, answer, citations | conversation record |

Tutor는 높은 재현율을 위해 chapter tag를 보조 신호로 사용하고 semantic
retrieval을 유지한다. 근거가 부족하면 모른다고 답하거나 추가 질문으로 전환한다.

## 최소 데이터 스키마

- `documents`: `source`, `document_id`, `title`, `content`, `source_url`, `source_locator`, `text_hash`, `dataset_version`
- `chunks`: 위 lineage + `chunk_id`, `chunk_index`, `token_count`
- `chunk_classifications`: `chunk_id`, `chapter_id`, `relevance_score`, `reason`, `subtopics`, `evidence_span`, `quiz_candidate`, `needs_review`, `model_name`, `classified_at`, `prompt_version`, `rubric_version`, `review_status`
- `question_drafts`: `question_id`, `chapter_id`, `evidence_chunk_ids`, `draft_payload`, `validation_status`, `human_review_status`
- `conversations/messages`: existing Node.js ownership policy와 API contract를 우선하며 이번 단계에서 migration을 추가하지 않는다.

## 책임 경계

Python 전처리는 원문 보존·정규화·청크·후보·평가 파일을 생성한다. FastAPI는
LLM/RAG orchestration과 grounding을 담당한다. LlamaIndex는 query rewrite와
retrieval adapter다. PostgreSQL/pgvector는 원문·청크·embedding 저장소다. Node.js는
제품 API, 인증, 사용자 상태, 문제은행 게시를 담당한다. Human Reviewer는 챕터
관련성·출처·문제 적합성을 승인한다.
