-- File: migrations/003_create_jobs.sql

CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    url TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('greenhouse', 'lever', 'linkedin', 'indeed', 'workday', 'generic')),
    source TEXT NOT NULL CHECK (source IN ('telegram', 'discord', 'manual')),
    status TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN ('discovered', 'scored', 'approved', 'applying', 'applied', 'rejected', 'skipped', 'failed')),
    score INTEGER CHECK (score >= 0 AND score <= 100),
    raw_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, url)
);

CREATE INDEX idx_jobs_user_id ON jobs(user_id);
CREATE INDEX idx_jobs_status ON jobs(user_id, status);