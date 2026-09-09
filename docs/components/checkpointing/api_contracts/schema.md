# Checkpointing — API Contract

> **Owns:** None (no HTTP endpoints — database operations only)
> **Consumed by:** Core Engine via direct function imports
> **Canonical source:** `docs/api_contracts/schema.md` §15

---

## Internal Functions (Not HTTP)

Checkpointing is triggered by Core Engine pipeline steps. It does not expose HTTP endpoints.

---

## Table Owned

### checkpoints

```sql
CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    step TEXT NOT NULL CHECK (step IN ('jd_extraction', 'rubric_generation', 'scoring', 'optimization', 'package_generation')),
    pipeline_state JSONB NOT NULL DEFAULT '{}',
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_checkpoints_user_id ON checkpoints (user_id);
CREATE INDEX idx_checkpoints_job_id ON checkpoints (job_id);
```

---

## Save Checkpoint (Internal)

Called after each pipeline step completes:

```python
def save_checkpoint(
    user_id: str,
    job_id: str,
    step: str,
    pipeline_state: dict,
    error_message: str | None = None
) -> str:  # returns checkpoint_id
```

**Side effects:**
- INSERT into `checkpoints` table
- Logs `checkpoint_created` to `audit_logs`

---

## Resume Checkpoint (Internal)

Called when resuming a failed pipeline:

```python
def resume_checkpoint(
    checkpoint_id: str
) -> dict:  # returns { step, pipeline_state }
```

**Side effects:**
- SELECT from `checkpoints` table (ORDER BY created_at DESC, LIMIT 1)
- DELETE old checkpoints for this job after successful resume
- UPDATE `pipeline_runs.status = running`
- Logs `pipeline_resumed` to `audit_logs`

---

## Pipeline Steps (with checkpoint save after each)

```
Step 1: JD Extraction
  ├── Fetch career page
  ├── Parse + LLM extract
  └── CHECKPOINT → save structured_jd

Step 2: Rubric Generation
  ├── Generate role.json + criteria.jinja
  └── CHECKPOINT → save rubric_config

Step 3: Scoring
  ├── Score profile against rubric
  └── CHECKPOINT → save evaluation_result

Step 4: Optimization (if needed)
  ├── Rewrite sections
  ├── Re-score
  └── CHECKPOINT → save optimized_resume + new_score

Step 5: Package Generation
  ├── Generate PDF
  ├── Build field mappings
  └── CHECKPOINT → save package (ready for extension)
```

---

## Resume Flow

```
Failure at Step 3 (scoring):
  checkpoints table:
  ├── step: "scoring"
  ├── pipeline_state: {
  │     structured_jd: {...},  (from Step 1)
  │     rubric_config: {...}   (from Step 2)
  │   }
  └── error_message: "Gemini rate limited"

Resume:
  ├── Read checkpoint from DB
  ├── Skip Steps 1 + 2 (already saved)
  └── Restart at Step 3 with saved state
```

---

## Cleanup Policy

```
Completed checkpoints: deleted after 7 days
Failed checkpoints: kept for 30 days (for debugging)
Manual discard: immediate deletion
```

```sql
-- Cleanup completed checkpoints
DELETE FROM checkpoints
WHERE created_at < NOW() - INTERVAL '7 days'
  AND error_message IS NULL;

-- Cleanup failed checkpoints
DELETE FROM checkpoints
WHERE created_at < NOW() - INTERVAL '30 days'
  AND error_message IS NOT NULL;
```

---

## Data Flow (Internal)

```
PIPELINE FAILS:
  checkpointing → checkpoints (INSERT pipeline_state, step, error_message)

RESUME PIPELINE:
  checkpointing → checkpoints (SELECT by job_id, ORDER BY created_at DESC)
  checkpointing → checkpoints (DELETE old checkpoints after successful resume)

PIPELINE COMPLETES:
  checkpointing → checkpoints (DELETE all checkpoints for this job)

CLEANUP OLD:
  checkpointing → checkpoints (DELETE successful WHERE created_at < NOW() - 7 days)
  checkpointing → checkpoints (DELETE failed WHERE created_at < NOW() - 30 days)
```

---

## Audit Actions

| Internal Event | Audit Action | Resource Type |
|----------------|-------------|---------------|
| Checkpoint saved | `checkpoint_created` | checkpoint |
| Checkpoint resumed | `checkpoint_resumed` | checkpoint |
| Pipeline paused | `pipeline_paused` | checkpoint |
