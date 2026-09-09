# Auth — Schema

Tables owned by the auth component.

> **Canonical source:** `docs/database/schema.md` — migration 001 (users), 011 (api_keys), 013 (settings), 024 (user_profiles), 026 (auth_sessions).
> If any column differs here vs canonical, canonical wins.

---

## users

```sql
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
```

---

## api_keys

```sql
CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX idx_api_keys_prefix ON api_keys(prefix);
```

---

## settings

```sql
CREATE TABLE settings (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, key)
);
```

---

## user_profiles

```sql
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
```

---

## auth_sessions (migration 026) — server-side refresh-token revocation

Created by S3 (decision D9). Owned by auth; FORCE RLS like every other table.

```sql
CREATE TABLE auth_sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jti_hash    TEXT NOT NULL,              -- SHA-256 of the refresh-token jti (never raw)
    expires_at  TIMESTAMPTZ NOT NULL,        -- +7d at issue
    revoked_at  TIMESTAMPTZ,                 -- NULL = active; set by logout / refresh rotation
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX idx_auth_sessions_jti_hash ON auth_sessions(jti_hash);

ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON auth_sessions
    USING (user_id = current_setting('app.user_id')::uuid);
ALTER TABLE auth_sessions FORCE ROW LEVEL SECURITY;
```

### auth_user_by_email (SECURITY DEFINER — D10)

The single RLS bypass lane: lets login find a user by email at a point where the GUC is unset.

```sql
CREATE FUNCTION auth_user_by_email(email text)
RETURNS TABLE(id uuid, email text, password_hash text, name text)
LANGUAGE sql SECURITY DEFINER STABLE AS
$$ SELECT id, email, password_hash, name FROM users WHERE users.email = $1 LIMIT 1 $$;
GRANT EXECUTE ON FUNCTION auth_user_by_email(text) TO app_user;
```

Owner = `postgres` (migration-time). Returns one exact-match row only; leaks nothing else.
See `docs/architecture/security_boundaries.md` and decision D10 (`plans/steps/S3-auth.md:82`).
