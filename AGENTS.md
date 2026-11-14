# Leren AI 작업 가이드

## 코드 위치

- FastAPI 진입점: `main.py` → `app/main.py`
- HTTP 계약: `app/api/routes`, `app/api/v1/routers`, `app/schemas`
- 문제 생성: `app/question_generation`, 작업 상태: `app/question_generation/jobs.py`
- 튜터/RAG: `app/services/tutor_service.py`, `app/rag/pipeline.py`, `app/rag/retrieval`
- 저장 계층: `app/repositories`, `app/db`. DB 구조(SQL)는 백엔드 레포 `database/`가 기준 (이 레포에 migration 없음)
- 회귀 하네스: `tests/`; CI: `.github/workflows/test-ai.yml`

## 로컬 검증 순서

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python -m uvicorn main:app --reload
```

실행 후 `http://localhost:8000/docs`에서 내부 토큰(`X-Internal-API-Key`)을
사용해 `POST /internal/v1/questions/jobs`를 등록하고
`GET /internal/v1/questions/jobs/{jobId}`로 상태와 `PENDING_REVIEW` 문항을
확인한다. 튜터 내부 계약은 `POST /internal/v1/tutor/answer`이며, API 요약은
`docs/api_specification.md`, Node.js 경계는
`docs/TUTOR_INTERNAL_API_CONTRACT.md`에 있다.

CI는 외부 LLM 키 없이 고정 근거와 모의 모델로 실행한다. 실제 LLM·pgvector
품질/지연 평가는 별도 staging 실행이다.
