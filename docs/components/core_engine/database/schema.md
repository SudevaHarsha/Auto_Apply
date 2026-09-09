# Core Engine — Schema

Tables owned by the core engine component.

> **Canonical source:** `docs/database/schema.md` — migration 002 (profiles), 003 (jobs), 004 (applications), 015 (pipeline_runs), 025 (job_snapshots).
> If any column differs here vs canonical, canonical wins.

---

## profiles

```sql
CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_pdf_url TEXT NOT NULL,
    json_resume JSONB NOT NULL,
    last_scored_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_profiles_user_id ON profiles(user_id);
```

---

## jobs

```sql
CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    url TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('greenhouse', 'lever', 'linkedin', 'indeed', 'workday', 'generic')),
    source TEXT NOT NULL CHECK (source IN ('telegram', 'discord', 'manual')),
    status TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN ('discovered', 'scored', 'approved', 'applying', 'applied', 'rejected', 'skipped', 'failed')),
    score INTEGER CHECK (score >= 0 AND score <= 100),
    freshness_state TEXT NOT NULL DEFAULT 'fresh' CHECK (freshness_state IN ('fresh', 'stale', 'expired')),
    content_hash TEXT,
    current_snapshot_id UUID,
    last_fetched_at TIMESTAMPTZ,
    raw_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, url)
);

CREATE INDEX idx_jobs_user_id ON jobs(user_id);
CREATE INDEX idx_jobs_status ON jobs(user_id, status);
CREATE INDEX idx_jobs_freshness ON jobs(user_id, freshness_state);
```

---

## job_snapshots

Immutable, shared, RLS-exempt table backing both the extraction cache and JD truth/versioning.

> **Canonical source:** `docs/database/schema.md` — migration 025.

```sql
CREATE TABLE job_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_hash TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

No `user_id` by design — public job data, zero PII, one row serves every user sharing the same posting (shared-cache invariant). `content_hash` doubles as the cache key and the version fingerprint.

```sql
CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    optimized_resume JSONB NOT NULL,
    cover_letter TEXT,
    pdf_url TEXT NOT NULL,
    field_mappings JSONB NOT NULL,
    required_fields JSONB DEFAULT '[]'::jsonb,
    fill_details JSONB DEFAULT '[]'::jsonb,
    snapshot_id UUID REFERENCES job_snapshots(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'filling', 'filled', 'submitted', 'skipped', 'failed')),
    skip_reason TEXT,
    screenshot_url TEXT,
    filled_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_applications_user_id ON applications(user_id);
CREATE INDEX idx_applications_job_id ON applications(job_id);
CREATE INDEX idx_applications_status ON applications(user_id, status);
```

`fill_details` records every field attempt:
```jsonc
[
  {
    "label": "First Name",
    "value": "John",
    "filled": true,
    "error": null,
    "required": true,
    "tier": "deterministic"
  },
  {
    "label": "Why work at Stripe?",
    "value": "I'm drawn to...",
    "filled": true,
    "error": null,
    "required": true,
    "tier": "llm_fallback"
  }
]
```

`skip_reason` records fill-time blockers (SSO wall, CAPTCHA, unsupported platform, `expired` when `freshness_state = 'expired'`).

---

## pipeline_runs

```sql
CREATE TABLE pipeline_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'paused')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    steps_run TEXT[] NOT NULL DEFAULT '{}',
    total_time_ms INTEGER,
    error_message TEXT,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'auto')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pipeline_runs_job_id ON pipeline_runs(job_id);
CREATE INDEX idx_pipeline_runs_user_id ON pipeline_runs(user_id);
```
