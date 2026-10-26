# Migration ownership

The current ERD assigns `ai_conversations`, `ai_messages`,
`ai_message_sources`, and `ai_requests` to the Node.js backend. FastAPI must not
create or mutate those tables for the internal Tutor API.

`003_ai_conversations_and_rag.sql` and `004_multiturn_rag_p0.sql` are retained
as historical P0 compatibility migrations. They predate the final ownership
split and must not be applied to a shared database without an explicit
Node.js schema-owner review. FastAPI runtime startup does not execute migration
files, and `app.db.postgres.create_tables()` creates only FastAPI-owned local
tables.
