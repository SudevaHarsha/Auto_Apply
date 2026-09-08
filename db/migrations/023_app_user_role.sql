-- File: migrations/023_app_user_role.sql
-- NOTE (D3, doc divergence): CREATE ROLE is wrapped in an idempotent guard because
-- roles are cluster-wide and survive DROP DATABASE — re-running migrations on a
-- recreated DB would otherwise fail with "role already exists".
-- NOTE (D2, doc divergence): the doc FORCEs RLS on user_profiles here, but that
-- table is created in migration 024. That FORCE line moves to 024.

-- 1. Create dedicated app_user role (non-superuser, non-owner)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'app_user') THEN
        CREATE ROLE app_user LOGIN PASSWORD 'changeme_in_production';
    END IF;
END
$$;

-- Grant usage on public schema
GRANT USAGE ON SCHEMA public TO app_user;

-- Grant table permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;

-- 2. Apply FORCE ROW LEVEL SECURITY to the tenant tables that exist so far
--    (user_profiles is FORCEd in 024 after it is created -> 19 tables total)
ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE applications FORCE ROW LEVEL SECURITY;
ALTER TABLE evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE llm_providers FORCE ROW LEVEL SECURITY;
ALTER TABLE telegram_connections FORCE ROW LEVEL SECURITY;
ALTER TABLE discord_connections FORCE ROW LEVEL SECURITY;
ALTER TABLE discord_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE checkpoints FORCE ROW LEVEL SECURITY;
ALTER TABLE api_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE settings FORCE ROW LEVEL SECURITY;
ALTER TABLE provider_usage FORCE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE rate_limit_state FORCE ROW LEVEL SECURITY;
ALTER TABLE telegram_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE error_logs FORCE ROW LEVEL SECURITY;

-- 3. Connection string for FastAPI (use in .env)
-- DATABASE_URL=postgresql://app_user:<password>@localhost:5432/autoapply
-- (NOT postgres://... which would bypass RLS)