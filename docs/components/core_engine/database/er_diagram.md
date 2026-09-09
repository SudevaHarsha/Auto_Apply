# Core Engine — ER Diagram

Entity-Relationship diagram for tables owned by the core engine component.

---

## Diagram

```
  ┌──────────────────┐
  │    profiles      │
  ├──────────────────┤
  │ PK id      UUID  │
  │ FK user_id UUID  │
  │ original_        │
  │   pdf_url        │
  │ json_resume      │
  │  JSONB           │
  │ last_            │
  │   scored_at      │
  │ created_at       │
  │ updated_at       │
  └──────────────────┘
             └── 1:N ───────────────────────────────────────▼

  ┌───────────────────┐    ┌───────────────────┐
  │      jobs         │    │  applications     │
  ├───────────────────┤    ├───────────────────┤
  │ PK id      UUID   │    │ PK id        UUID │
  │ FK user_id UUID   │    │ FK user_id   UUID │
  │ title             │    │ FK job_id    UUID │
  │ company           │    │ FK profile_id UUID│
  │ url               │    │ optimized_        │
  │ platform          │    │  resume JSONB     │
  │ source            │    │ cover_letter      │
  │ status            │    │ pdf_url           │
  │ score             │    │ field_            │
  │ raw_message       │    │  mappings JSONB   │
  │ freshness_        │    │ required_         │
  │  state            │    │  fields JSONB     │
  │ content_hash      │    │ status            │
  │ current_          │    │ fill_details      │
  │  snapshot_        │    │ skip_reason       │
  │  id               │    │ snapshot_id       │
  │ last_             │    │ screenshot_       │
  │  fetched_at       │    │  url              │
  │ created_at        │    │ filled_at         │
  │ updated_at        │    │ submitted_at      │
  └───────────────────┘    │ created_at        │
                           └───────────────────┘

           │                       │
           │ 1:N                       │ 1:N
           ▼                       ▼
    ┌───────────────────┐    ┌───────────────────┐
    │  pipeline_runs    │    │    evidence       │
    ├───────────────────┤    ├───────────────────┤
    │ PK id      UUID   │    │ PK id        UUID │
    │ FK user_id UUID   │    │ FK application    │
    │ FK job_id  UUID   │    │   _id             │
    │ status            │    │ FK user_id   UUID │
    │ started_at        │    │ type              │
    │ completed_at      │    │ file_url          │
    │ steps_run []      │    │ metadata JSONB    │
    │ total_time_ms     │    │ created_at        │
    │ error_message     │    └───────────────────┘
    │ trigger           │
    │ created_at        │
    └───────────────────┘

  ┌───────────────────┐   (shared, RLS-exempt — no user_id)
  │  job_snapshots    │
  ├───────────────────┤
  │ PK id      UUID   │
  │ content_hash TEXT │
  │ payload JSONB     │
  │ captured_at       │
  └───────────────────┘

    jobs.current_snapshot_id ──────> job_snapshots.id
    applications.snapshot_id ──────> job_snapshots.id
```

---

## Relationships

```
profiles (1) ─────< (N) applications            via FK profile_id
jobs (1) ───────< (N) applications            via FK job_id
applications (1) ─< (N) evidence               via FK application_id
jobs (1) ───────< (N) pipeline_runs            via FK job_id
jobs.current_snapshot_id ──> job_snapshots     FK (0..1 per job)
applications.snapshot_id ──> job_snapshots     FK (0..1 per application)
```

---

## Cross-Component Reads

```
core_engine READS FROM:
  └── llm_providers (for scoring, optimization, JD extraction)
  └── provider_usage (logs token usage)
  └── checkpoints (resumes failed pipelines)
  └── audit_logs (INSERT job/application events)
  └── evidence (reads evidence for status display)
  └── user_profiles (fallback for missing resume fields)
```
