-- File: migrations/031_create_rubric_cache.sql
-- Rubric persistence (S7 D58, Option B): the generated rubric is a property of the JD snapshot,
-- NOT of a user — shared table, RLS-exempt (same pattern as job_snapshots).
-- One row per (job, snapshot, schema_version); rubric_sha256 guards the cached content.
CREATE TABLE rubric_cache (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    job_id          UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    snapshot_id     UUID NOT NULL,
    schema_version  INTEGER NOT NULL CHECK (schema_version = 1),  -- CURRENT_SCHEMA_VERSION at ship; a
                                                                  -- bump is a deliberate re-generation seam
    rubric          JSONB NOT NULL,   -- role.json shape + rendered criteria/system (+ labels/weights)
    rubric_sha256   TEXT NOT NULL,    -- content guard, recomputed on read (cache-integrity check)
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX idx_rubric_cache_key
    ON rubric_cache (job_id, snapshot_id, schema_version);
