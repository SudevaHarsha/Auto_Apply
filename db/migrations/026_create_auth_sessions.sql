-- File: migrations/026_create_auth_sessions.sql
-- NOTE (D9, doc divergence): server-side session revocation store backing
-- POST /api/auth/logout and refresh-token rotation. Added by S3; every parity
-- artifact (run_migrations invariants, golden dump, docs inventory, RLS matrix,
-- ownership map) is reconciled in the same commit (plans/steps/S3-auth.md §8).
-- NOTE (D10): auth_user_by_email is the narrow SECURITY DEFINER login lookup —
-- the only path into `users` outside RLS (the GUC is unset at login time). It is
-- STABLE, returns at most one exact-match row, and is owned by the migration user
-- (cluster superuser), never used elsewhere.

CREATE TABLE auth_sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jti_hash    TEXT NOT NULL,              -- SHA-256 of the refresh-token jti (never raw)
    expires_at  TIMESTAMPTZ NOT NULL,       -- +7d at issue; matches refresh TTL
    revoked_at  TIMESTAMPTZ,                -- NULL = active; set by logout / refresh rotation
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX idx_auth_sessions_jti_hash ON auth_sessions(jti_hash);

-- Tenant isolation, consistent with every user-owned table (ENABLE + FORCE + policy).
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions FORCE ROW LEVEL SECURITY;

CREATE POLICY user_isolation ON auth_sessions
    USING (user_id = current_setting('app.user_id')::uuid);

-- D10: single-row, exact-email login lookup for app_user (SECURITY DEFINER carve-out).
CREATE OR REPLACE FUNCTION auth_user_by_email(p_email text)
RETURNS TABLE (id uuid, email text, password_hash text, name text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id, email, password_hash, name
    FROM users
    WHERE email = p_email
    LIMIT 1;
$$;

GRANT EXECUTE ON FUNCTION auth_user_by_email(text) TO app_user;