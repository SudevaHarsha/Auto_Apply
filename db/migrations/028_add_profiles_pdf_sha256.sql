-- Migration 028 — S5: pdf_sha256 for DB-level idempotent upload detection (D23).
-- Column is nullable: existing rows stay NULL; only new uploads get a hash.
-- Partial unique index: one profile row per (user_id, sha256-of-PDF).
-- RLS: unchanged — user_isolation covers the new column transparently.

ALTER TABLE profiles ADD COLUMN pdf_sha256 TEXT;

CREATE UNIQUE INDEX idx_profiles_user_sha256
  ON profiles(user_id, pdf_sha256)
  WHERE pdf_sha256 IS NOT NULL;
