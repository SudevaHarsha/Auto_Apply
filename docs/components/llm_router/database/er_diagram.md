# LLM Router — ER Diagram

Entity-Relationship diagram for tables owned by the LLM router component.

---

## Diagram

```
┌─────────────────┐
│  llm_providers  │
├─────────────────┤
│PK id       UUID │
│FK user_id  UUID │
│   name         │
│   base_url     │
│   api_key_     │
│    encrypted   │
│   model        │
│   is_active    │
│   priority     │
│   created_at   │
│   updated_at   │
└────────┬────────┘
         │
         │ 1:N
         ▼
┌───────────────────┐
│  provider_usage   │
├───────────────────┤
│PK id          UUID │
│FK user_id     UUID │
│FK provider_id UUID │
│FK job_id      UUID │  (nullable)
│   prompt_tokens    │
│   completion_      │
│    tokens          │
│   latency_ms       │
│   success          │
│   error_type       │
│   created_at       │
└───────────────────┘


┌───────────────────┐
│ rate_limit_state  │
├───────────────────┤
│PK id          UUID │
│   provider_name    │
│FK user_id     UUID │
│   state            │  OPEN/CLOSED/HALF_OPEN
│   failure_count    │
│   last_failure_at  │
│   cooldown_        │
│    expires_at      │
│   created_at       │
│   updated_at       │
└───────────────────┘
```

---

## Legend

```
PK = Primary Key
FK = Foreign Key
1:N = One-to-Many
```

---

## Cross-Component Reads

```
llm_router READS FROM:
  └── audit_logs (INSERT provider failures, circuit events)
```

USED BY:
  └── core_engine (calls llm_router for scoring, optimization)
