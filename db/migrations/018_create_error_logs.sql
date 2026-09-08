-- File: migrations/018_create_error_logs.sql

CREATE TABLE error_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    component TEXT NOT NULL,
    error_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO')),
    message TEXT NOT NULL,
    context JSONB,
    provider TEXT,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_action TEXT,
    stack_trace TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_error_logs_user_id ON error_logs(user_id);
CREATE INDEX idx_error_logs_component ON error_logs(component);
CREATE INDEX idx_error_logs_severity ON error_logs(severity);
CREATE INDEX idx_error_logs_job_id ON error_logs(job_id);
CREATE INDEX idx_error_logs_created_at ON error_logs(created_at);