-- File: migrations/010_create_telegram_connections.sql

CREATE TABLE telegram_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bot_token TEXT NOT NULL,  -- encrypted with AES-256 via application layer
    bot_username TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'disconnected' CHECK (status IN ('connected', 'disconnected', 'error')),
    groups JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_telegram_connections_user_id ON telegram_connections(user_id);
