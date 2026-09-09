# Checkpointing — Schema

> **Canonical source:** `docs/database/schema.md` — migration 006 (checkpoints).

SQL for tables owned by the checkpointing component.

---

## checkpoints

```sql
CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    pipeline_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    step TEXT NOT NULL CHECK (step IN ('jd_extraction', 'rubric_generation', 'scoring', 'optimization', 'package_generation')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_checkpoints_user_id ON checkpoints(user_id);
CREATE INDEX idx_checkpoints_job_id ON checkpoints(job_id);

-- RLS
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
CREATE POLICY checkpoints_isolated ON checkpoints
    USING (user_id = current_setting('app.user_id')::uuid);
```
