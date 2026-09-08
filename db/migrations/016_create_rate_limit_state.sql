-- File: migrations/016_create_rate_limit_state.sql

CREATE TABLE rate_limit_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_name TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'CLOSED' CHECK (state IN ('OPEN', 'CLOSED', 'HALF_OPEN')),
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_failure_at TIMESTAMPTZ,
    cooldown_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(provider_name, user_id)
);

CREATE INDEX idx_rate_limit_provider_user ON rate_limit_state(provider_name, user_id);