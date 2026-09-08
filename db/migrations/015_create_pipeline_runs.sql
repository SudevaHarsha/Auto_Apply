-- File: migrations/015_create_pipeline_runs.sql

CREATE TABLE pipeline_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'paused')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    steps_run TEXT[] NOT NULL DEFAULT '{}',
    total_time_ms INTEGER,
    error_message TEXT,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'auto')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pipeline_runs_job_id ON pipeline_runs(job_id);
CREATE INDEX idx_pipeline_runs_user_id ON pipeline_runs(user_id);