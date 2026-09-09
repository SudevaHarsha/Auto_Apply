# Frontend — ER Diagram

Entity-Relationship diagram showing the user-facing tables rendered by the frontend (job_snapshots is internal/shared, not surfaced).

---

## Diagram

```
┌─────────────────┐
│      users       │──── ProfileMenu, SettingsPage
├─────────────────┤
│ PK id       UUID │
│    email    TEXT │
│    ...          │
└────────┬────────┘
         │
    ┌────┴──────────────────────────────────────────┐
    │            │               │                   │
    ▼            ▼               ▼                   ▼
┌──────────┐ ┌──────────┐ ┌────────────┐      ┌───────────┐
│ profiles │ │   jobs   │ │ llm_       │      │telegram_  │
├──────────┤ ├──────────┤ │ providers  │      │connections│
│ResumePage│ │JobBoard  │ ├────────────┤      ├───────────┤
└──────────┘ │JobCard   │ │ProvidersPg│      │TelegramPg │
             └──────────┘ └────────────┘      └───────────┘
                 │
                 ▼
          ┌──────────────┐
          │ applications │──── ApplicationsTable, AppCard
          ├──────────────┤
          └──────┬───────┘
                 │
                 ▼
          ┌──────────────┐
          │   evidence   │──── EvidenceGallery
          ├──────────────┤
          └──────────────┘

┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│  audit_logs   │  │  api_keys     │  │  settings     │
├───────────────┤  ├───────────────┤  ├───────────────┤
│AuditLogPage   │  │APIKeysPage    │  │SettingsPage   │
└───────────────┘  └───────────────┘  └───────────────┘

┌───────────────┐  ┌───────────────┐  ┌───────────────┐
│provider_usage │  │pipeline_runs  │  │rate_limit_    │
├───────────────┤  ├───────────────┤  │  state        │
│UsageStats     │  │PipelineHistory│  ├───────────────┤
└───────────────┘  └───────────────┘  │ProviderStatus │
                                      └───────────────┘

┌───────────────┐  ┌───────────────────┐  ┌─────────────────┐
│  checkpoints  │  │  error_logs       │  │discord_         │
├───────────────┤  ├───────────────────┤  │  connections    │
│PausedJobs     │  │ErrorLogPage       │  ├─────────────────┤
└───────────────┘  └───────────────────┘  │DiscordPage      │
                                          └─────────────────┘

┌──────────────────┐  ┌──────────────────┐  ┌──────────────────┐
│telegram_messages │  │discord_messages  │  │  user_profiles   │
├──────────────────┤  ├──────────────────┤  ├──────────────────┤
│MessageHistory    │  │DiscordHistory    │  │UserProfilePage   │
└──────────────────┘  └──────────────────┘  └──────────────────┘
```

---

## Access Pattern

```
Frontend renders the user-facing tables (read-only access); job_snapshots is internal/shared and not rendered
No direct DB access — fetches via Backend API
```
