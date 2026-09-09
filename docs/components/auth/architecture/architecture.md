# Auth — FastAPI JWT + RLS Integration

Email/password auth with JWT sessions. RLS enforced via dedicated `app_user` role + `SET LOCAL app.user_id`.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    AUTHENTICATION + RLS FLOW                      │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Registration                                              │   │
│  │                                                            │   │
│  │  ┌──────────┐     ┌──────────┐     ┌──────────────────┐   │   │
│  │  │ Signup   │────▶│ FastAPI   │────▶│ bcrypt hash      │   │   │
│  │  │ Form     │     │ /register │     │ password         │   │   │
│  │  └──────────┘     └──────────┘     └────────┬─────────┘   │   │
│  │                                             │             │   │
│  │                                             ▼             │   │
│  │                                    ┌──────────────────┐   │   │
│  │                                    │ INSERT INTO      │   │   │
│  │                                    │ users table      │   │   │
│  │                                    └────────┬─────────┘   │   │
│  │                                             │             │   │
│  │                                             ▼             │   │
│  │                                    ┌──────────────────┐   │   │
│  │                                    │ Issue JWT pair   │   │   │
│  │                                    │ (Bearer, 15 min)│   │   │
│  │                                    └──────────────────┘   │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Login                                                     │   │
│  │                                                            │   │
│  │  ┌──────────┐     ┌──────────┐     ┌──────────────────┐   │   │
│  │  │ Login    │────▶│ FastAPI   │────▶│ Verify hash      │   │   │
│  │  │ Form     │     │ /login    │     │ with bcrypt      │   │   │
│  │  └──────────┘     └──────────┘     └────────┬─────────┘   │   │
│  │                                             │             │   │
│  │                                   ┌─────────┴─────────┐   │   │
│  │                                   │                   │   │   │
│  │                              valid_hash          invalid_hash│ │
│  │                                   │                   │   │   │
│  │                                   ▼                   ▼   │   │
│  │                          ┌────────────────┐  ┌─────────┐  │   │
│  │                          │ Issue JWT pair │  │ 401     │  │   │
│  │                          │ (Bearer 15 min)│  │ Invalid │  │   │
│  │                          │ + 7d refresh  │  │ creds   │  │   │
│  │                          └────────────────┘  └─────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  JWT Token Structure                                      │   │
│  │                                                            │   │
│  │  {                                                        │   │
│  │    "sub": "user-uuid",                                    │   │
│  │    "email": "user@example.com",                           │   │
│  │    "exp": 1724300000,                                     │   │
│  │    "iat": 1724213600                                      │   │
│  │  }                                                        │   │
│  │                                                            │   │
│  │  Secret: stored in env var (JWT_SECRET)                    │   │
│  │  JWT exp: 15 min                                            │   │
│  │  Refresh: 7 days; revoked server-side via jti               │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Auth Middleware (FastAPI)                                 │   │
│  │                                                            │   │
│  │  Every /api/* request (except /register, /login):          │   │
│  │  ├── Extract JWT from Bearer                              │   │
│  │  ├── Verify signature                                     │   │
│  │  ├── Check expiry                                         │   │
│  │  ├── Extract user_id from token                           │   │
│  │  └── Attach to request context                            │   │
│  │                                                            │   │
│  │  If invalid: return 401 → frontend redirects to /login     │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  RLS Enforcement (app_user role + SET LOCAL)               │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Database Roles:                                     │  │   │
│  │  │                                                      │  │   │
│  │  │  postgres (superuser)                                │  │   │
│  │  │  ├── Runs migrations only                            │  │   │
│  │  │  ├── Creates tables, indexes, policies               │  │   │
│  │  │  └── NEVER used by FastAPI at runtime                │  │   │
│  │  │                                                      │  │   │
│  │  │  app_user (non-superuser, non-owner)                 │  │   │
│  │  │  ├── CONNECT, SELECT, INSERT, UPDATE, DELETE         │  │   │
│  │  │  ├── Does NOT own any tables                         │  │   │
│  │  │  ├── RLS applies (non-owner + non-superuser)         │  │   │
│  │  │  └── FastAPI connects as this role                   │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  FORCE ROW LEVEL SECURITY                            │  │   │
│  │  │                                                      │  │   │
│  │  │  -- Applied to all tables after RLS policies:        │  │   │
│  │  │  ALTER TABLE profiles FORCE ROW LEVEL SECURITY;      │  │   │
│  │  │  ALTER TABLE jobs FORCE ROW LEVEL SECURITY;          │  │   │
│  │  │  ALTER TABLE applications FORCE ROW LEVEL SECURITY;  │  │   │
│  │  │  ALTER TABLE evidence FORCE ROW LEVEL SECURITY;      │  │   │
│  │  │  ALTER TABLE llm_providers FORCE ROW LEVEL SECURITY; │  │   │
│  │  │  ... (all 19 tables)                                 │  │   │
│  │  │                                                      │  │   │
│  │  │  FORCE ensures RLS applies even if app_user somehow  │  │   │
│  │  │  becomes table owner (e.g., migration grants).       │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Per-Transaction SET LOCAL (correct pattern)         │  │   │
│  │  │                                                      │  │   │
│  │  │  async def get_db_with_rls(                          │  │   │
│  │  │      user: User = Depends(get_user)                  │  │   │
│  │  │  ):                                                  │  │   │
│  │  │      async with session_factory() as session:        │  │   │
│  │  │          # SET LOCAL scoped to this transaction      │  │   │
│  │  │          # Auto-clears at commit/rollback            │  │   │
│  │  │          # No leakage between requests               │  │   │
│  │  │          await session.execute(                      │  │   │
│  │  │              text("SET LOCAL app.user_id = :uid"),   │  │   │
│  │  │              {"uid": str(user.id)}                    │  │   │
│  │  │          )                                           │  │   │
│  │  │          yield session                               │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Why NOT event.listens_for("connect"):               │  │   │
│  │  │                                                      │  │   │
│  │  │  SQLAlchemy pools connections. "connect" fires once   │  │   │
│  │  │  per pool checkout, not per request.                 │  │   │
│  │  │                                                      │  │   │
│  │  │  Request 1 (user A): SET LOCAL user_id = A           │  │   │
│  │  │  Connection returned to pool                         │  │   │
│  │  │  Request 2 (user B): reuses same connection          │  │   │
│  │  │  → user_id is still A from last SET LOCAL            │  │   │
│  │  │  → user B sees user A's data                         │  │   │
│  │  │                                                      │  │   │
│  │  │  SET LOCAL auto-clears at transaction end, but       │  │   │
│  │  │  pool checkout is not a transaction boundary.        │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Result:                                             │  │   │
│  │  │                                                      │  │   │
│  │  │  FastAPI connects as app_user (non-superuser)        │  │   │
│  │  │  RLS enforced via policies + FORCE ROW LEVEL SECURITY│  │   │
│  │  │  SET LOCAL scoped per-request via FastAPI dependency │  │   │
│  │  │                                                      │  │   │
│  │  │  SELECT * FROM jobs;                                  │  │   │
│  │  │  → Only returns jobs WHERE user_id = current user    │  │   │
│  │  │                                                      │  │   │
│  │  │  Even if handler forgets WHERE user_id =:            │  │   │
│  │  │  → RLS policy filters automatically                  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Extension Auth                                            │   │
│  │                                                            │   │
│  │  Extension uses same JWT cookie as the frontend.           │   │
│  │  ├── User logs in via dashboard first                      │   │
│  │  ├── Extension shares the browser session (same origin)    │   │
│  │  └── No separate auth flow for extension                   │   │
│  │                                                            │   │
│  │  API key auth for MCP server:                              │   │
│  │  ├── User generates API key in dashboard                   │   │
│  │  ├── Stores key in env var for local agent                 │   │
│  │  └── MCP server uses key to authenticate to backend        │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Migration: app_user Role

```sql
-- File: migrations/023_app_user_role.sql

-- 1. Create dedicated app role (non-superuser, non-owner)
CREATE ROLE app_user LOGIN PASSWORD 'changeme_in_production';
GRANT CONNECT ON DATABASE autoapply TO app_user;
GRANT USAGE ON SCHEMA public TO app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;

-- 2. Apply FORCE ROW LEVEL SECURITY to all 19 tables
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
ALTER TABLE user_profiles FORCE ROW LEVEL SECURITY;

-- 3. Connection string for FastAPI (use in .env)
-- DATABASE_URL=postgresql://app_user:<password>@localhost:5432/autoapply
-- (NOT postgres://... which would bypass RLS)
```

---

## Canonical corrections (S3 — D6, D8, D9, D10)

> In-force transport and flows, superseding any stale box-diagram labels above.
> Cross-reference: `plans/steps/S3-auth.md` §2.2 (decision log D6–D12).

1. **Transport (D8):** tokens travel as `Authorization: Bearer <access_token>` — **no cookie in
   the API contract**. Access tokens expire in **15 minutes**, refresh tokens in **7 days**. An
   optional httpOnly cookie is a frontend (S18) transport concern only.
2. **Register (D6):** the app **pre-generates `uuid4()`** and inserts `users` with an explicit
   `id`. Under `FORCE RLS` with `WITH CHECK = USING (id = GUC)`, a DB-generated id could never
   satisfy the policy; the pre-generated id is the caller's real identity.
3. **Logout (D9):** `POST /api/auth/logout` (Bearer refresh token) revokes the session
   **server-side** in `auth_sessions` (migration 026): `UPDATE ... SET revoked_at = NOW() WHERE
   jti_hash = SHA-256(jti) AND revoked_at IS NULL`. After logout the old refresh token can no
   longer rotate. Logout emits **no audit action** (canonical set is closed).
4. **Login lookup (D10):** `SELECT users WHERE email=…` is impossible for `app_user` under RLS
   because the GUC is unset at login. Login uses the SECURITY DEFINER function
   `auth_user_by_email(email)` (migration 026) — single row, exact email, owner `postgres`,
   `EXECUTE` granted to `app_user`. Documented carve-out; `users` RLS otherwise intact.
