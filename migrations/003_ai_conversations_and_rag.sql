CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS ai_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id VARCHAR(255) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ai_conversations_user_id ON ai_conversations(user_id);

CREATE TABLE IF NOT EXISTS ai_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    role VARCHAR(20) NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ai_messages_conversation_id_created_at
    ON ai_messages(conversation_id, created_at);

CREATE TABLE IF NOT EXISTS rag_documents (
    document_id VARCHAR(255) PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    source VARCHAR(1000) NOT NULL,
    version VARCHAR(100),
    content_hash VARCHAR(64) NOT NULL UNIQUE,
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS rag_document_chunks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id VARCHAR(255) NOT NULL REFERENCES rag_documents(document_id) ON DELETE CASCADE,
    chunk_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    embedding vector(1536),
    metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE(document_id, chunk_id)
);
CREATE INDEX IF NOT EXISTS ix_rag_document_chunks_document_id ON rag_document_chunks(document_id);
