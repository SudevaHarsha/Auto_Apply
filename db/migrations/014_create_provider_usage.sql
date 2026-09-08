-- File: migrations/014_create_provider_usage.sql

CREATE TABLE provider_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES llm_providers(id) ON DELETE CASCADE,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    error_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_provider_usage_job_id ON provider_usage(job_id);
CREATE INDEX idx_provider_usage_provider_id ON provider_usage(provider_id);
CREATE INDEX idx_provider_usage_user_id ON provider_usage(user_id);