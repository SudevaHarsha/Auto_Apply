-- File: migrations/025_job_snapshots_freshness.sql

-- 1. Add freshness state to jobs (user-scoped, RLS protects it)
ALTER TABLE jobs
    ADD COLUMN freshness_state TEXT NOT NULL DEFAULT 'fresh'
        CHECK (freshness_state IN ('fresh', 'stale', 'expired')),
    ADD COLUMN content_hash TEXT,
    ADD COLUMN current_snapshot_id UUID,
    ADD COLUMN last_fetched_at TIMESTAMPTZ;

CREATE INDEX idx_jobs_freshness ON jobs(user_id, freshness_state);

-- 2. Shared job snapshots table (PUBLIC job data — NO user_id, RLS-exempt)
--    Stores immutable extraction results keyed by content fingerprint.
--    One extraction serves all users who see the same posting.
CREATE TABLE job_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_hash TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,          -- full structured JD output (Door 1-5 result)
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Bind applications/rubrics to the snapshot version they were scored against
ALTER TABLE applications
    ADD COLUMN snapshot_id UUID REFERENCES job_snapshots(id) ON DELETE SET NULL;

ALTER TABLE jobs
    ADD CONSTRAINT fk_jobs_snapshot
        FOREIGN KEY (current_snapshot_id) REFERENCES job_snapshots(id) ON DELETE SET NULL;

-- 4. Freshness transition function (triggered on fetch / age)
CREATE OR REPLACE FUNCTION apply_freshness_fsm() RETURNS trigger AS $$
BEGIN
    IF NEW.freshness_state = 'fresh' AND OLD.freshness_state <> 'fresh' THEN
        NEW.freshness_state = 'fresh';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
