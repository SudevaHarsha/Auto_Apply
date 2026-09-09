# Backend API — Database Scope

No tables owned. HTTP layer that reads/writes all tables via service functions.

---

## Tables Accessed

```
TABLE                READ    WRITE    WHY
─────────────────────────────────────────────────────
users                ✓       ✓       auth endpoints
profiles             ✓       ✓       resume CRUD
jobs                 ✓       ✓       job CRUD, scoring
applications         ✓       ✓       application CRUD
evidence             ✓       ✓       evidence upload/list
llm_providers        ✓       ✓       provider CRUD
telegram_connections ✓       ✓       bot management
discord_connections  ✓       ✓       Discord bot management
discord_messages     ✓       ✓       Discord message history
checkpoints          ✓       ✓       pipeline resume
api_keys             ✓       ✓       API key management
audit_logs           ✓       ✓       audit log display
error_logs           ✓       ✗       error log display (READ only)
settings             ✓       ✓       preferences CRUD
user_profiles        ✓       ✓       supplemental personal info
provider_usage       ✓       ✓       usage tracking
pipeline_runs        ✓       ✓       pipeline history (core_engine owns)
rate_limit_state     ✓       ✓       circuit management
telegram_messages    ✓       ✓       message history
job_snapshots        ✓       ✗       shared JD snapshot cache (core_engine writes)
```

---

## Access Pattern

```
Backend API does not own tables — it delegates to service functions:
  auth_service       → users, api_keys, settings, user_profiles
  job_service        → jobs, applications, profiles
  pipeline_service   → checkpoints, pipeline_runs
  llm_service        → llm_providers, provider_usage, rate_limit_state
  discovery_service  → telegram_connections, telegram_messages
  discord_service    → discord_connections, discord_messages
  evidence_service   → evidence
  audit_service      → audit_logs, error_logs
```

---

## RLS Enforcement

```
All queries go through FastAPI with SET LOCAL app.user_id
RLS policies on each table enforce user isolation
Backend API connects as app_user (non-superuser), sets user_id per transaction
```
