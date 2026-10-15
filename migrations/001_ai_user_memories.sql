CREATE TABLE IF NOT EXISTS ai_user_memories (
    id UUID PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    source VARCHAR(255),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
