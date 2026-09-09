-- File: migrations/004_create_applications.sql

CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    optimized_resume JSONB NOT NULL,
    cover_letter TEXT,
    pdf_url TEXT NOT NULL,
    field_mappings JSONB NOT NULL,
    required_fields JSONB DEFAULT '[]'::jsonb,
    fill_details JSONB DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'filling', 'filled', 'submitted', 'skipped', 'failed')),
    skip_reason TEXT,
    screenshot_url TEXT,
    filled_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_applications_user_id ON applications(user_id);
CREATE INDEX idx_applications_job_id ON applications(job_id);
CREATE INDEX idx_applications_status ON applications(user_id, status);
