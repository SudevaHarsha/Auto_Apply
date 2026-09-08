-- File: migrations/005_create_llm_providers.sql

CREATE TABLE llm_providers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (name IN ('gemini', 'ollama', 'groq', 'openrouter')),
    base_url TEXT NOT NULL,
    api_key_encrypted TEXT,
    model TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_llm_providers_user_id ON llm_providers(user_id);
CREATE INDEX idx_llm_providers_priority ON llm_providers(user_id, priority);