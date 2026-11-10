-- Question-generation workflow state.  A job and its questions are owned by the
-- internal backend/queue; only COMPLETED jobs contain reviewable questions.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS ai_question_generation_jobs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    request_id UUID NOT NULL UNIQUE,
    request_fingerprint VARCHAR(64) NOT NULL,
    execution_status VARCHAR(20) NOT NULL,
    review_status VARCHAR(30),
    failure_step VARCHAR(80),
    failure_code VARCHAR(80),
    failure_detail VARCHAR(1000),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    request_json JSONB NOT NULL,
    result_json JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ai_question_generation_questions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id UUID NOT NULL REFERENCES ai_question_generation_jobs(id) ON DELETE CASCADE,
    question_index INTEGER NOT NULL CHECK (question_index >= 0),
    review_status VARCHAR(30) NOT NULL CHECK (review_status = 'PENDING_REVIEW'),
    question_json JSONB NOT NULL,
    evidence_references_json JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (job_id, question_index)
);

CREATE INDEX IF NOT EXISTS ix_ai_question_generation_jobs_status
    ON ai_question_generation_jobs(execution_status, updated_at);
