-- Non-destructive P0 upgrade. Existing conversations/documents are preserved.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

ALTER TABLE ai_conversations ADD COLUMN IF NOT EXISTS stage_id VARCHAR(255);
ALTER TABLE ai_conversations ADD COLUMN IF NOT EXISTS concept_id VARCHAR(255);
ALTER TABLE ai_conversations
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active';
CREATE INDEX IF NOT EXISTS ix_ai_conversations_stage_id ON ai_conversations(stage_id);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_concept_id ON ai_conversations(concept_id);

ALTER TABLE ai_messages ADD COLUMN IF NOT EXISTS sequence_no INTEGER;
ALTER TABLE ai_messages ADD COLUMN IF NOT EXISTS request_id VARCHAR(255);
ALTER TABLE ai_messages
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'completed';
ALTER TABLE ai_messages
    ADD COLUMN IF NOT EXISTS grounded BOOLEAN NOT NULL DEFAULT FALSE;

WITH ordered AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY conversation_id ORDER BY created_at, id
           ) AS generated_sequence
    FROM ai_messages
    WHERE sequence_no IS NULL
)
UPDATE ai_messages AS message
SET sequence_no = ordered.generated_sequence
FROM ordered
WHERE message.id = ordered.id;

ALTER TABLE ai_messages ALTER COLUMN sequence_no SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_ai_message_sequence'
    ) THEN
        ALTER TABLE ai_messages
            ADD CONSTRAINT uq_ai_message_sequence
            UNIQUE (conversation_id, sequence_no);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'uq_ai_message_request_role'
    ) THEN
        ALTER TABLE ai_messages
            ADD CONSTRAINT uq_ai_message_request_role
            UNIQUE (request_id, role);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_ai_messages_request_id ON ai_messages(request_id);

CREATE TABLE IF NOT EXISTS ai_message_sources (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    message_id UUID NOT NULL REFERENCES ai_messages(id) ON DELETE CASCADE,
    source_id VARCHAR(255) NOT NULL,
    document_id VARCHAR(255) NOT NULL,
    chunk_id VARCHAR(255) NOT NULL,
    document_version VARCHAR(100),
    title_snapshot VARCHAR(500),
    source_url VARCHAR(2000),
    CONSTRAINT uq_ai_message_source UNIQUE (message_id, document_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS ix_ai_message_sources_message_id
    ON ai_message_sources(message_id);

ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS source_id VARCHAR(255);
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS source_url VARCHAR(2000);
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS concept_id VARCHAR(255);
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS stage_id VARCHAR(255);
ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS review_status VARCHAR(30) NOT NULL DEFAULT 'approved';
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS published_at TIMESTAMPTZ;
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ;
ALTER TABLE rag_documents ADD COLUMN IF NOT EXISTS license VARCHAR(255);
UPDATE rag_documents SET source_id = document_id WHERE source_id IS NULL;
ALTER TABLE rag_documents ALTER COLUMN source_id SET NOT NULL;
CREATE INDEX IF NOT EXISTS ix_rag_documents_source_id ON rag_documents(source_id);
CREATE INDEX IF NOT EXISTS ix_rag_documents_concept_id ON rag_documents(concept_id);
CREATE INDEX IF NOT EXISTS ix_rag_documents_stage_id ON rag_documents(stage_id);
CREATE INDEX IF NOT EXISTS ix_rag_documents_review_status ON rag_documents(review_status);

CREATE TABLE IF NOT EXISTS rag_index_configurations (
    collection_name VARCHAR(255) PRIMARY KEY,
    embedding_provider VARCHAR(100) NOT NULL,
    embedding_model VARCHAR(255) NOT NULL,
    embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
