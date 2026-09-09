# Observability — ER Diagram

Entity-Relationship diagram for tables owned by the observability component.

---

## Diagram

```
┌─────────────────┐
│   audit_logs    │
├─────────────────┤
│PK id       UUID │
│FK user_id  UUID │
│   action        │
│   resource_     │
│    type         │
│   resource_id   │
│   details  JSONB│
│   ip_address    │
│   created_at    │
└─────────────────┘

    (INSERT ONLY — immutable)


┌─────────────────┐
│   error_logs    │
├─────────────────┤
│PK id       UUID │
│FK user_id  UUID │
│   component     │
│   error_type    │
│   severity      │
│   message       │
│   context  JSONB│
│   provider      │
│FK job_id   UUID │  (nullable)
│   retry_count   │
│   next_action   │
│   stack_trace   │
│   created_at    │
└─────────────────┘

    (INSERT ONLY — immutable)

NOTE: pipeline_runs moved to core_engine (see core_engine/database/er_diagram.md)
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
observability READS FROM:
  └── audit_logs (aggregates for dashboard)
  └── error_logs (aggregates for dashboard)

USED BY:
  └── ALL components (write audit_logs for every action)
  └── ALL components (write error_logs on failure)
```

---

## Immutability

```
audit_logs  — INSERT ONLY, no UPDATE, no DELETE
error_logs  — INSERT ONLY, no UPDATE, no DELETE
  enforced by PostgreSQL triggers
```
