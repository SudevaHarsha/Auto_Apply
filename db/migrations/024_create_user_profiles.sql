-- File: migrations/024_create_user_profiles.sql
-- NOTE (D4, doc divergence): the doc FORCEs RLS on user_profiles (023) but the table
-- is created here and is never given ENABLE RLS or any policy — with FORCE RLS and
-- zero policies the table would be wholly inaccessible. This migration therefore
-- adds ENABLE RLS (D2: moved FORCE) and the user_isolation policy so the table is
-- properly tenant-scoped, consistent with every other user-owned table.

CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    phone TEXT,
    linkedin_url TEXT,
    github_url TEXT,
    website_url TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    postal_code TEXT,
    date_of_birth DATE,
    gender TEXT,
    ethnicity TEXT,
    veteran_status TEXT,
    disability_status TEXT,
    work_authorization TEXT,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id)
);

CREATE INDEX idx_user_profiles_user_id ON user_profiles(user_id);

-- D4: RLS completeness for user_profiles (ENABLE + FORCE + policy)
ALTER TABLE user_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE user_profiles FORCE ROW LEVEL SECURITY;

CREATE POLICY user_isolation ON user_profiles
    USING (user_id = current_setting('app.user_id')::uuid);