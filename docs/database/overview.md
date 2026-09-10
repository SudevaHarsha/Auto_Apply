# Database Architecture — Complete Overview

All tables, relationships, and data flow across the system.

---

## Canonical Source of Truth

```
docs/database/schema.md is the ONLY place tables/columns/enums/statuses are defined.

Component docs may reference them ("uses jobs.status enum, see database/schema.md")
but never redefine them.

If you need to add a column, enum value, or new table:
  1. Edit docs/database/schema.md first
  2. Update the component doc that owns it
  3. Do NOT redefine in multiple places
```

---

## Per-Component Database Docs

Each component has its own database folder with overview, schema, and ER diagram:

| Component | Tables Owned | Location |
|-----------|-------------|----------|
| auth | users, api_keys, settings, user_profiles | `components/auth/database/` |
| core_engine | profiles, jobs, applications, pipeline_runs, job_snapshots | `components/core_engine/database/` |
| discovery | telegram_connections, telegram_messages | `components/discovery/database/` |
| discord | discord_connections, discord_messages | `components/discord/database/` |
| llm_router | llm_providers, provider_usage, rate_limit_state | `components/llm_router/database/` |
| checkpointing | checkpoints | `components/checkpointing/database/` |
| observability | audit_logs, error_logs | `components/observability/database/` |
| chrome_extension | evidence | `components/chrome_extension/database/` |
| backend_api | (reads all, owns none) | `components/backend_api/database/` |
| frontend | (reads all, owns none) | `components/frontend/database/` |
| mcp_engine | (reads all, owns none) | `components/mcp_engine/database/` |

---

## Complete Schema Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              AUTOAPPLY DATABASE                                  │
│                          PostgreSQL (Docker Compose or Supabase)                    │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐
│      users       │
├─────────────────┤
│ id         UUID │──── PK
│ email      TEXT │──── UNIQUE, NOT NULL
│ password_hash   │──── bcrypt hashed
│ name       TEXT │
│ created_at      │
│ updated_at      │
└────────┬────────┘
         │
         │ 1:N (user owns all their data)
         │
    ┌────┴──────────────────────────────────────────────┐
    │                    │                    │          │
    ▼                    ▼                    ▼          ▼
┌──────────┐      ┌──────────┐      ┌──────────┐  ┌──────────┐
│ profiles │      │   jobs   │      │ llm_     │  │telegram_ │
├──────────┤      ├──────────┤      │ providers│  │connections│
│ id  UUID │      │ id  UUID │      ├──────────┤  ├──────────┤
│ user_id  │ FK   │ user_id  │ FK   │ id  UUID │  │ id  UUID │
│ original_│      │ title    │      │ user_id  │FK│ user_id  │FK
│ pdf_url  │      │ company  │      │ name     │  │ bot_token│
│ json_    │      │ url      │      │ base_url │  │ bot_     │
│ resume   │ JSONB│ platform │      │ api_key_ │  │ username │
│ last_    │      │ source   │      │ encrypted│  │ status   │
│ scored_at│      │ status   │      │ model    │  │ groups   │ JSONB
│ created_ │      │ score    │      │ is_active│  │ created_ │
│ at       │      │ raw_     │      │ priority │  │ at       │
└────┬─────┘      │ message  │      │ created_ │  └──────────┘
     │            │ created_ │      │ at       │
     │            │ at       │      │ updated_ │
     │            │ updated_ │      │ at       │
     │            │ at       │      └──────────┘
     │            │ freshness│
     │            │ state    │
     │            │ content_ │
     │            │ hash     │
     │            │ current_ │
     │            │ snapshot │
     │            │ id       │
     │            │ last_    │
     │            │ fetched_ │
     │            │ at       │
     │            └────┬─────┘
     │                 │
     │                 │ 1:N
     │                 ▼
     │            ┌──────────────┐
     │            │ applications │
     │            ├──────────────┤
     │            │ id      UUID │
     ├── FK ─────<│ profile_id   │
     │            │ user_id  FK  │
     │            │ job_id   FK  │
     ├── FK ─────<│ optimized_   │
     │            │ resume  JSONB│
     │            │ cover_letter │
     │            │ pdf_url      │
     │            │ field_       │
     │            │ mappings JSONB│
     │            │ status       │
     │            │ required_     │
     │            │ fields        │
     │            │ fill_details  │
     │            │ skip_reason   │
     │            │ snapshot_id   │
     │            │ screenshot_  │
     │            │ url          │
     │            │ filled_at    │
     │            │ submitted_at │
     │            │ created_at   │
     │            └──────┬───────┘
     │                   │
     │                   │ 1:N
     │                   ▼
     │            ┌──────────────┐
     │            │  evidence    │
     │            ├──────────────┤
     │            │ id      UUID │
     │            │ application_ │
     │            │ id      FK   │
     │            │ user_id  FK   │
     │            │ type         │ screenshot/pdf/dom_
     │            │              │ snapshot/profile_diff/
     │            │              │ jd_raw/message_raw
     │            │ file_url     │
     │            │ metadata JSONB│
     │            │ created_at   │
     │            └──────────────┘
     │
     │ 1:N
     ▼
┌──────────────┐      ┌──────────────┐
│ checkpoints  │      │  api_keys    │
├──────────────┤      ├──────────────┤
│ id      UUID │      │ id      UUID │
│ user_id  FK  │      │ user_id  FK  │
│ job_id   FK  │      │ key_hash     │ hashed API key
│ pipeline_    │      │ name         │ user label
│ state  JSONB │      │ prefix       │ first 8 chars (for display)
│ step         │      │ last_used_at │
│ error_       │      │ expires_at   │ optional
│ message      │      │ created_at   │
│ created_at   │      └──────────────┘
│ updated_at   │
└──────────────┘

┌──────────────┐      ┌──────────────┐
│  audit_logs  │      │  settings    │
├──────────────┤      ├──────────────┤
│ id      UUID │      │ user_id  FK  │
│ user_id  FK  │      │ key          │ threshold_score
│ action       │      │ value    JSONB│ auto_approve
│ resource_type│      │ created_at   │ telegram_config
│ resource_id  │      │ updated_at   │ notification_pref
│ details JSONB│      └──────────────┘
│ ip_address   │
│ created_at   │
└──────────────┘

┌───────────────┐     ┌───────────────┐     ┌───────────────┐
│provider_usage │     │pipeline_runs  │     │rate_limit_    │
├───────────────┤     ├───────────────┤     │  state        │
│ id      UUID  │     │ id      UUID  │     ├───────────────┤
│ user_id  FK  │     │ user_id  FK   │     │ id      UUID  │
│ provider_idFK│     │ job_id   FK   │     │ provider_name │
│ job_id   FK  │     │ status        │     │ user_id  FK   │
│ prompt_      │     │ started_at    │     │ state         │
│  tokens  INT │     │ completed_at  │     │ OPEN/CLOSED/  │
│ completion_  │     │ steps_run []  │     │  HALF_OPEN    │
│  tokens  INT │     │ total_time_ms │     │ failure_count │
│ latency_ms   │     │ error_message │     │ last_failure_ │
│ success      │     │ trigger       │     │  at           │
│ error_type   │     │  (manual/auto)│     │ cooldown_     │
│ created_at   │     │ created_at    │     │  expires_at   │
└───────────────┘     └───────────────┘     │ created_at    │
                                           │ updated_at    │
                                           └───────────────┘

┌──────────────────┐
│telegram_messages  │
├──────────────────┤
│ id      UUID     │
│ user_id  FK      │
│ chat_id   BIGINT │
│ chat_title TEXT  │
│ message_id BIGINT│
│ text       TEXT  │
│ urls_found []TEXT│
│ job_created BOOL │
│ job_id     FK    │
│ created_at       │
└──────────────────┘

┌──────────────────┐     ┌───────────────────┐
│  error_logs      │     │  user_profiles    │
├──────────────────┤     ├───────────────────┤
│ id      UUID     │     │ id       UUID     │
│ user_id  FK      │     │ user_id  FK       │
│ component TEXT   │     │ phone     TEXT    │
│ level    TEXT    │     │ linkedin  TEXT    │
│ message  TEXT    │     │ github    TEXT    │
│ context  JSONB   │     │ address   TEXT    │
│ created_at       │     │ dob       TEXT    │
└──────────────────┘     │ custom_   JSONB   │
                         │  fields           │
                         │ created_at        │
                         │ updated_at        │
                         └───────────────────┘

┌───────────────────┐    ┌───────────────────┐
│discord_connections│    │  discord_messages  │
├───────────────────┤    ├───────────────────┤
│ id       UUID     │    │ id       UUID     │
│ user_id  FK       │    │ user_id  FK       │
│ bot_token TEXT    │    │ server_id BIGINT  │
│ bot_username TEXT │    │ server_name TEXT  │
│ status    TEXT    │    │ channel_id BIGINT │
│ chat_mode TEXT    │    │ channel_name TEXT │
│ notif_enabled BOOL│    │ message_id BIGINT │
│ notif_events []   │    │ author_id BIGINT  │
│ servers   JSONB   │    │ is_dm     BOOL    │
│ created_at        │    │ direction TEXT    │
│ updated_at        │    │ text      TEXT    │
└───────────────────┘    │ urls_found []TEXT │
                         │ job_created BOOL  │
                         │ job_id     FK     │
                         │ created_at        │
                         └───────────────────┘

┌───────────────────┐
│  job_snapshots    │   (shared, RLS-exempt — no user_id)
├───────────────────┤
│ id        UUID    │
│ content_hash TEXT │ UNIQUE
│ payload   JSONB   │
│ captured_at       │
└───────────────────┘
```

---

## Table Purposes

```
TABLE                PURPOSE                              OWNER
─────────────────────────────────────────────────────────────────
users                Account + auth credentials            system
profiles             Parsed resume (JSONResume)            user
jobs                 Discovered job postings                user
applications         Per-job application package           user
evidence             Screenshots, PDFs, DOM snapshots      user
llm_providers        User's LLM provider config            user
telegram_connections Bot token + subscribed groups          user
checkpoints          Pipeline state for resume              user
api_keys             API keys for MCP/local agent           user
audit_logs           Immutable action log                   user
error_logs           Structured error log per component     user
settings             User preferences (JSON)                user
provider_usage       Per-request LLM usage tracking         user
pipeline_runs        Full pipeline execution history        user
rate_limit_state     Circuit breaker state (persisted)      user
telegram_messages    Raw Telegram message log               user
discord_connections  Discord bot token + servers            user
discord_messages     Raw Discord message log               user
user_profiles        Supplemental personal info            user
job_snapshots        Shared immutable JD extraction cache  shared (RLS-exempt)
```

---

## Key Relationships

```
users (1) ──────────< (N) profiles
users (1) ──────────< (N) jobs
users (1) ──────────< (N) applications
users (1) ──────────< (N) evidence
users (1) ──────────< (N) llm_providers
users (1) ──────────< (N) telegram_connections
users (1) ──────────< (N) checkpoints
users (1) ──────────< (N) api_keys
users (1) ──────────< (N) audit_logs
users (1) ──────────< (N) error_logs
users (1) ──────────< (N) settings
users (1) ──────────< (N) provider_usage
users (1) ──────────< (N) pipeline_runs
users (1) ──────────< (N) rate_limit_state
users (1) ──────────< (N) telegram_messages
users (1) ──────────< (N) discord_connections
users (1) ──────────< (N) discord_messages
users (1) ──────────── (1) user_profiles

profiles (1) ────────< (N) applications
jobs (1) ────────────< (N) applications
jobs (1) ────────────< (N) checkpoints
jobs (1) ────────────< (N) pipeline_runs
jobs (1) ────────────< (N) provider_usage
jobs (1) ──────────── (0..1) job_snapshots  (jobs.current_snapshot_id → job_snapshots.id)
applications (1) ────< (N) evidence
applications (1) ──── (0..1) job_snapshots  (applications.snapshot_id → job_snapshots.id)
telegram_messages (1) ──── (0..1) jobs (if URL found → job created)
llm_providers (1) ────< (N) provider_usage
```

---

## Missing From Current Schema (Added Below)

```
1. evidence              ← proof storage (screenshots, PDFs, DOM)
2. telegram_connections  ← bot token, subscribed groups, status
3. api_keys              ← MCP server auth (hashed, prefixed)
4. audit_logs            ← immutable action tracking
5. settings              ← user preferences (threshold, auto-approve)
6. provider_usage        ← per-request LLM usage (tokens, latency, success, error_type)
7. pipeline_runs         ← full execution history (start, end, steps)
8. rate_limit_state      ← circuit breaker persistence across restarts
9. telegram_messages     ← raw message log (for debugging, replay)
```

---

## Data Flow Through Tables

```
UPLOAD RESUME:
  users → profiles (json_resume stored)

DISCOVER JOB:
  users → jobs (title, url, platform, status=discovered)
  users → telegram_messages (raw message logged)
  users → audit_logs (action: job_discovered)

EXTRACT & SNAPSHOT (JD):
  job_snapshots (INSERT payload keyed by content_hash; reuse on cache hit)
  jobs → jobs (current_snapshot_id, freshness_state, last_fetched_at)
  jobs → applications (snapshot_id on package creation)

SCORE JOB:
  jobs → jobs (score updated, status=scored)
  jobs → provider_usage (tokens, latency, success logged)
  jobs → audit_logs (action: job_scored)

APPROVE JOB:
  jobs → jobs (status=approved)
  users → audit_logs (action: job_approved)

CREATE APPLICATION:
  jobs + profiles → applications (optimized_resume, pdf_url, field_mappings, required_fields, fill_details=[])
  jobs → pipeline_runs (run started)
  users → audit_logs (action: application_created)

FILL FORM (Extension — Tier 1 deterministic match):
  applications → applications (status=filling, fill_details: tier=deterministic)
  users → audit_logs (action: application_filled)

FILL FORM (Extension — Tier 2 LLM fallback for unmapped fields):
  applications → applications (fill_details: tier=llm_fallback)
  llm_router → provider_usage (token usage)
  users → audit_logs (action: llm_fill_request)

FILL BLOCKED (SSO / CAPTCHA / unsupported platform / expired):
  applications → applications (status=skipped, skip_reason=<reason>)
  jobs → jobs (freshness_state stale→expired; this is what blocks fill → applications.skip_reason='expired')

SUBMIT (User clicks submit):
  applications → applications (status=submitted, submitted_at)
  applications → evidence (screenshot captured)
  users → audit_logs (action: application_submitted)
  jobs → pipeline_runs (run completed)

PROVIDER FAILS:
  jobs → checkpoints (pipeline_state saved, step, error_message)
  users → rate_limit_state (circuit breaker opened)
  users → audit_logs (action: llm_provider_failed)

RESUME PIPELINE:
  checkpoints → (skip completed steps, restart from saved step)
  users → audit_logs (action: pipeline_resumed)

ALL PROVIDERS DOWN:
  users → rate_limit_state (all circuits open)
  users → audit_logs (action: all_providers_exhausted)
```

---

## Indexes (Common Queries)

```sql
-- Fast lookups for:
idx_profiles_user_id           -- "get my profile"
idx_jobs_user_id               -- "get my jobs"
idx_jobs_status                -- "get my jobs by status"
idx_jobs_freshness             -- "jobs by freshness (fresh/stale/expired)"
idx_applications_user_id       -- "get my applications"
idx_applications_job_id        -- "get application for this job"
idx_checkpoints_job_id         -- "resume this job's pipeline"
idx_llm_providers_user_id      -- "get my provider chain"
idx_telegram_connections_user_id -- "get my bot config"
idx_api_keys_prefix            -- "look up API key by prefix"
idx_audit_logs_user_id         -- "my action history"
idx_evidence_application_id    -- "get evidence for this app"
idx_provider_usage_job_id      -- "usage for this job"
idx_provider_usage_provider_id -- "usage by this provider"
idx_pipeline_runs_job_id       -- "execution history for job"
idx_rate_limit_provider_user   -- "circuit state for provider+user"
idx_telegram_messages_user_id  -- "my message history"
idx_telegram_messages_chat     -- "messages from this chat"
idx_applications_status        -- "my applications by status"
idx_api_keys_user_id           -- "all my API keys"
idx_audit_logs_action          -- "audit trail by action"
idx_checkpoints_user_id        -- "all my resume points"
idx_evidence_user_id           -- "all my evidence"
idx_llm_providers_priority     -- "ordered provider chain"
idx_pipeline_runs_user_id      -- "all my pipeline history"
idx_provider_usage_user_id     -- "usage across my jobs"
idx_user_profiles_user_id      -- "my profile versions"
idx_users_email                -- "login lookup (email)"
```
