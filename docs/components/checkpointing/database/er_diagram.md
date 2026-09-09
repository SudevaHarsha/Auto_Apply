# Checkpointing — ER Diagram

Entity-Relationship diagram for tables owned by the checkpointing component.

---

## Diagram

```
┌─────────────────┐
│   checkpoints   │
├─────────────────┤
│PK id       UUID │
│FK user_id  UUID │
│FK job_id   UUID │
│   pipeline_     │
│    state   JSONB│
│   step          │
│   error_        │
│    message      │
│   created_at    │
│   updated_at    │
└─────────────────┘
```

---

## Legend

```
PK = Primary Key
FK = Foreign Key
```

---

## Cross-Component Reads

```
checkpointing READS FROM:
  └── jobs (loads job context for resume)
  └── audit_logs (INSERT resume events)

USED BY:
  └── core_engine (saves/loads pipeline state on failure/resume)
```
