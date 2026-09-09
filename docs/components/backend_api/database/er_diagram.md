# Backend API — ER Diagram

Entity-Relationship diagram showing all tables accessed by the backend API.

---

## Diagram

```
                               ┌─────────────────┐
                               │      users       │
                               ├─────────────────┤
                               │ PK id       UUID │
                               │    email    TEXT │
                               │    ...          │
                               └────────┬────────┘
                                        │
     ┌──────────────────────────────────┼──────────────────────────────────────┐
     │            │                     │                     │                │
     ▼            ▼                     ▼                     ▼                ▼
┌──────────┐ ┌──────────┐      ┌────────────┐      ┌────────────┐    ┌───────────┐
│ profiles │ │   jobs   │      │ llm_       │      │telegram_   │    │ settings  │
├──────────┤ ├──────────┤      │ providers  │      │connections │    ├───────────┤
│          │ │          │      ├────────────┤      ├────────────┤    │           │
└──────────┘ └──────────┘      └────────────┘      └────────────┘    └───────────┘
    │            │                     │                    │
    │            │                     │                    │
    ▼            ▼                     ▼                    ▼
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│  applications    │      │  provider_usage  │      │ rate_limit_state │
├──────────────────┤      ├──────────────────┤      ├──────────────────┤
│                  │      │                  │      │                  │
└──────────────────┘      └──────────────────┘      └──────────────────┘
    │
    ▼
┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│    evidence      │      │  checkpoints     │      │  pipeline_runs   │
├──────────────────┤      ├──────────────────┤      ├──────────────────┤
│                  │      │                  │      │                  │
└──────────────────┘      └──────────────────┘      └──────────────────┘

┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│   audit_logs     │      │  api_keys        │      │telegram_messages │
├──────────────────┤      ├──────────────────┤      ├──────────────────┤
│                  │      │                  │      │                  │
└──────────────────┘      └──────────────────┘      └──────────────────┘

┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│   error_logs     │      │discord_connections│     │discord_messages  │
├──────────────────┤      ├──────────────────┤      ├──────────────────┤
│                  │      │                  │      │                  │
└──────────────────┘      └──────────────────┘      └──────────────────┘

┌──────────────────┐
│  user_profiles   │
├──────────────────┤
│ phone, linkedin, │
│ github, address, │
│ dob, custom_fields│
└──────────────────┘

┌──────────────────┐
│  job_snapshots   │  (shared, RLS-exempt)
├──────────────────┤
│ content_hash,    │
│ payload,         │
│ captured_at      │
└──────────────────┘
```

---

## Access Pattern

```
Backend API reads/writes ALL 20 tables
No tables owned — delegates to service functions
RLS enforced via SET LOCAL app.user_id per transaction
job_snapshots is read-only (shared cache, no user_id)
```
