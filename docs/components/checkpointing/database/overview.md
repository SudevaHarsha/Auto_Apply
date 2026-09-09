# Checkpointing — Database Scope

Owns pipeline state persistence for resume-on-failure.

---

## Tables Owned

```
TABLE        PURPOSE                              WRITES
────────────────────────────────────────────────────────
checkpoints  Pipeline state for resume             CREATE, UPDATE, DELETE
```

---

## Tables Read

```
TABLE             READ BY              WHY
────────────────────────────────────────────────────
jobs              checkpointing        loads job context for resume
```

---

## Tables Written (INSERT only, no ownership)

```
TABLE             WRITER               WHY
────────────────────────────────────────────────────
audit_logs        checkpointing        logs resume events (INSERT)
```

---

## Data Flow

```
PIPELINE FAILS:
  checkpointing → checkpoints (INSERT pipeline_state, step, error_message)

RESUME PIPELINE:
  checkpointing → checkpoints (SELECT by job_id, ORDER BY created_at DESC)
  checkpointing → checkpoints (DELETE old checkpoints after successful resume)

PIPELINE COMPLETES:
  checkpointing → checkpoints (DELETE all checkpoints for this job)

CLEANUP OLD:
  checkpointing → checkpoints (DELETE successful checkpoints WHERE created_at < NOW() - INTERVAL '7 days')
  checkpointing → checkpoints (DELETE failed checkpoints WHERE created_at < NOW() - INTERVAL '30 days')
```

---

## Relationships

```
users (1) ──────< (N) checkpoints
jobs (1) ────────< (N) checkpoints
```
