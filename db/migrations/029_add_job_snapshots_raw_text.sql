-- File: migrations/029_add_job_snapshots_raw_text.sql
-- Persists the CLEANED JD text the cascade produced (D28, S6) — never raw HTML.
-- Column-only: no table, no index → runner invariants (21 tables / 40 idx / 20 RLS / 22 policies) unchanged.
ALTER TABLE job_snapshots ADD COLUMN raw_text TEXT;