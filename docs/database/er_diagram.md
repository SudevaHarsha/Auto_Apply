# ER Diagram — AutoApply Database

Entity-Relationship diagram with crow's foot notation.

---

## Diagram

```
                               ┌─────────────────┐
                               │      users       │
                               ├─────────────────┤
                               │ PK id       UUID │
                               │    email    TEXT │
                               │    password_... │
                               │    name     TEXT │
                               │    created_at   │
                               │    updated_at   │
                               └────────┬────────┘
                                        │
           ┌────────────────────────────┼─────────────────────────────────────────────┐
           │            │               │               │               │             │
           │ 1:N       │ 1:N          │ 1:1           │ 1:N           │ 1:N        │ 1:N
           ▼            ▼               ▼               ▼               ▼             ▼
    ┌───────────┐ ┌───────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌───────────┐
    │ profiles  │ │   jobs    │ │llm_        │ │telegram_   │ │  api_keys  │ │ settings  │
    ├───────────┤ ├───────────┤ │ providers  │ │connections │ ├────────────┤ ├───────────┤
    │PK id      │ │PK id      │ ├────────────┤ ├────────────┤ │PK id       │ │PK user_id │
    │FK user_id │ │FK user_id │ │PK id       │ │PK id       │ │FK user_id  │ │FK user_id │
    │   original│ │   title   │ │FK user_id  │ │FK user_id  │ │   key_hash │ │   key     │
    │   _pdf_url│ │   company │ │   name     │ │   bot_token│ │   name     │ │   value   │
    │   json_   │ │   url     │ │   base_url │ │   bot_     │ │   prefix   │ │   created_│
    │   resume  │ │   platform│ │   api_key_ │ │   username │ │   last_    │ │   at      │
    │   last_   │ │   source  │ │   encrypted│ │   status   │ │   used_at  │ │   updated_│
    │   scored_ │ │   status  │ │   model    │ │   groups   │ │   expires_ │ │   at      │
    │   at      │ │   score   │ │   is_active│ │   created_ │ │   at       │ └───────────┘
    │   created_│ │   raw_    │ │   priority │ │   at       │ │   created_ │
    │   at      │ │   message │ │   created_ │ └────────────┘ │   at       │
    └─────┬─────┘ │   created_│ │   at       │                └────────────┘
          │       │   at      │ │   updated_ │
          │       │   updated_│ │   at       │
          │       │   at      │ └─────┬──────┘
          │       │ freshness │              │
          │       │ state     │              │
          │       │ content_  │              │
          │       │ hash      │              │
          │       │ current_  │              │
          │       │ snapshot_ │              │
          │       │ id        │              │
          │       │ last_     │              │
          │       │ fetched   │              │
          │       │ at        │              │
          │       └─────┬─────┘       │
          │             │             │ 1:N
          │             │             ▼
          │             │      ┌──────────────┐
          │             │      │provider_usage│
          │             │      ├──────────────┤
          │             │      │PK id         │
          │             │      │FK user_id    │
          │             │      │FK provider_id│
          │             │      │FK job_id     │
          │             │      │   prompt_    │
          │             │      │    tokens    │
          │             │      │   completion_│
          │             │      │    tokens    │
          │             │      │   latency_ms │
          │             │      │   success    │
          │             │      └──────────────┘
          │             │
          │             │ 1:N
          │             ├──────────────────────────────────────────────┐
          │             │                      │                       │
          │             ▼                      ▼                       ▼
          │      ┌──────────────┐      ┌──────────────┐      ┌──────────────┐
          │      │ applications │      │ checkpoints  │      │pipeline_runs │
          │      ├──────────────┤      ├──────────────┤      ├──────────────┤
          │      │PK id         │      │PK id         │      │PK id         │
      FK   │      │FK user_id    │      │FK user_id    │      │FK user_id    │
      ─────┤      │FK job_id     │      │FK job_id     │      │FK job_id     │
          │      │FK profile_id │      │   pipeline_  │      │   status     │
          │      │   optimized_ │      │    state     │      │   started_at │
          │      │    resume    │      │   step       │      │   completed_ │
          │      │   cover_     │      │   error_     │      │    at        │
          │      │    letter    │      │    message   │      │   steps_run  │
          │      │   pdf_url    │      │   created_at │      │   total_     │
          │      │   field_     │      │   updated_at │      │    time_ms   │
          │      │    mappings  │      └──────────────┘      │   error_     │
          │      │   required_  │                             │    message   │
          │      │    fields    │                             │   trigger    │
          │      │   status     │                             │   created_at │
          │      │   fill_      │
          │      │   details    │
          │      │   skip_      │
          │      │   reason     │
          │      │   snapshot   │
          │      │   id         │
          │      │   screenshot_│                             └──────────────┘
          │      │    url       │
          │      │   filled_at  │
          │      │   submitted_ │
          │      │    at        │
          │      │   created_at │
          │      └──────┬───────┘
          │             │
          │             │ 1:N
          │             ▼
          │      ┌──────────────┐
          │      │  evidence    │
          │      ├──────────────┤
          │      │PK id         │
          │      │FK application│
          │      │   _id        │
          │      │FK user_id    │
          │      │   type       │
          │      │   file_url   │
          │      │   metadata   │
          │      │   created_at │
          │      └──────────────┘

           ┌──────────────────┐
           │  user_profiles   │
           ├──────────────────┤
           │PK id        UUID │
           │FK user_id   UUID │ 1:1
           │   phone      TEXT│
           │   linkedin_  TEXT│
           │    url            │
           │   github_url TEXT│
           │   website_   TEXT│
           │    url            │
           │   address    TEXT│
           │   city       TEXT│
           │   state      TEXT│
           │   country    TEXT│
           │   postal_    TEXT│
           │    code           │
           │   date_of_   DATE│
           │    birth          │
           │   gender     TEXT│
           │   ethnicity  TEXT│
           │   veteran_   TEXT│
           │    status         │
           │   disability TEXT│
           │    _status        │
           │   work_      TEXT│
           │    authorization  │
           │   custom_ JSONB │
           │    fields         │
           │   created_at     │
           │   updated_at     │
           └──────────────────┘

   ┌───────────────┐     ┌──────────────────┐
   │  audit_logs   │     │telegram_messages  │
   ├───────────────┤     ├──────────────────┤
   │PK id          │     │PK id             │
   │FK user_id     │     │FK user_id        │
   │   action      │     │   chat_id        │
   │   resource_   │     │   chat_title     │
   │    type       │     │   message_id     │
   │   resource_id │     │   text           │
   │   details     │     │   urls_found     │
   │   ip_address  │     │   job_created    │
   │   created_at  │     │FK job_id (nullable)│
   └───────────────┘     │   created_at     │
                         └──────────────────┘

   ┌───────────────────┐   ┌──────────────────┐   ┌─────────────────┐
   │  error_logs       │   │discord_connections│   │discord_messages │
   ├───────────────────┤   ├──────────────────┤   ├─────────────────┤
   │PK id              │   │PK id             │   │PK id            │
   │FK user_id         │   │FK user_id        │   │FK user_id       │
   │   component       │   │   bot_token      │   │   channel_id    │
   │   error_type      │   │   bot_username   │   │   message_id    │
   │   severity        │   │   servers  JSONB │   │   text          │
   │   message         │   │   status         │   │   urls_found    │
   │   context   JSONB │   │   created_at     │   │   job_created   │
   │   provider        │   │   updated_at     │   │FK job_id (nullable)│
   │FK job_id (nullable)│  └──────────────────┘   │   created_at    │
   │   retry_count     │                           └─────────────────┘
   │   stack_trace     │   ┌──────────────────┐
   │   created_at      │   │rate_limit_state  │
   └───────────────────┘   ├──────────────────┤
                            │PK id             │
                            │   provider_name  │
                            │FK user_id        │
                            │   state          │
                            │   failure_count  │
                            │   last_failure_at│
                            │   cooldown_      │
                            │    expires_at    │
                            │   created_at     │
                            │   updated_at     │
                            └──────────────────┘

   ┌───────────────────────┐
   │  job_snapshots        │   (shared, RLS-exempt — no user_id)
   ├───────────────────────┤
   │PK id             UUID │
   │   content_hash   TEXT │ UNIQUE
   │   payload        JSONB│
   │   captured_at         │
   └───────────────────────┘
```

---

## Legend

```
Symbol   Meaning
──────   ──────────────────────────────────
PK       Primary Key
FK       Foreign Key
1:N      One-to-Many
1:1      One-to-One
<        Crow's foot (many side)
─────    Connection line
```

---

## Relationships Summary

```
users ──────< profiles              1 user has N profiles
users ──────< jobs                  1 user has N jobs
users ──────< applications          1 user has N applications
users ──────< evidence              1 user has N evidence
users ──────< llm_providers         1 user has N providers
users ──────< telegram_connections  1 user has N bot connections
users ──────< checkpoints           1 user has N checkpoints
users ──────< api_keys              1 user has N API keys
users ──────< audit_logs            1 user has N log entries
users ─────── settings              1 user has N settings rows (user_id, key)
users ──────< provider_usage        1 user has N usage records
users ──────< pipeline_runs         1 user has N runs
users ──────< rate_limit_state      1 user has N circuit states
users ──────< telegram_messages     1 user has N messages
users ──────< discord_connections   1 user has N discord bots
users ──────< discord_messages      1 user has N discord messages
users ──────< error_logs            1 user has N error entries
users ─────── user_profiles         1 user has 1 profile row (supplemental info)

profiles ──────< applications       1 profile used in N applications
jobs ──────────< applications       1 job has N applications
jobs ──────────< checkpoints        1 job has N checkpoints
jobs ──────────< pipeline_runs      1 job has N runs
jobs ──────────< provider_usage     1 job has N usage records
applications ──< evidence           1 application has N evidence
telegram_messages ──> jobs          1 message may create 0..1 job
discord_messages ──> jobs            1 message may create 0..1 job
llm_providers ──< provider_usage    1 provider has N usage records
```
