-- File: migrations/009_create_evidence.sql

CREATE TABLE evidence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id UUID REFERENCES applications(id) ON DELETE CASCADE,  -- NULL for profile_diff, jd_raw, message_raw
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('screenshot', 'pdf', 'dom_snapshot', 'profile_diff', 'jd_raw', 'message_raw')),
    file_url TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_evidence_application_id ON evidence(application_id);
CREATE INDEX idx_evidence_user_id ON evidence(user_id);
