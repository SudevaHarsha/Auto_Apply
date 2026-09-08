-- File: migrations/017_create_telegram_messages.sql

CREATE TABLE telegram_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    chat_title TEXT,
    message_id BIGINT NOT NULL,
    text TEXT,
    urls_found TEXT[] NOT NULL DEFAULT '{}',
    job_created BOOLEAN NOT NULL DEFAULT FALSE,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, chat_id, message_id)
);

CREATE INDEX idx_telegram_messages_user_id ON telegram_messages(user_id);
CREATE INDEX idx_telegram_messages_chat ON telegram_messages(user_id, chat_id);