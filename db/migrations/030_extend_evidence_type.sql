-- File: migrations/030_extend_evidence_type.sql
-- Scoring facet evidence (S7 D52): canonical per I7 — one rubric_evidence row per rubric facet,
-- payload in metadata.json, file_url is an internal sentinel (no file written pre-package).
ALTER TABLE evidence DROP CONSTRAINT evidence_type_check;
ALTER TABLE evidence ADD CONSTRAINT evidence_type_check
    CHECK (type IN ('screenshot', 'pdf', 'dom_snapshot', 'profile_diff',
                    'jd_raw', 'message_raw', 'rubric_evidence'));
