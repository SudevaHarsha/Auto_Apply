# Discovery — ER Diagram

Entity-Relationship diagram for tables owned by the discovery component.

---

## Diagram

```
┌───────────────────────┐
│ telegram_connections  │
├───────────────────────┤
│PK id              UUID │
│FK user_id         UUID │
│   bot_token          │
│   bot_username       │
│   status             │
│   groups         JSONB│
│   created_at         │
└───────────────────────┘


┌───────────────────────┐
│  telegram_messages    │
├───────────────────────┤
│PK id              UUID │
│FK user_id         UUID │
│   chat_id     BIGINT  │
│   chat_title        TEXT│
│   message_id BIGINT  │
│   text            TEXT │
│   urls_found    TEXT[] │
│   job_created BOOLEAN │
│FK job_id (nullable)    │
│   created_at         │
└───────────┬───────────┘
            │
            │ 0..1
            ▼
    ┌───────────────┐
    │     jobs      │  (owned by core_engine)
    ├───────────────┤
    │PK id      UUID │
    │   ...          │
    └───────────────┘
```

---

## Legend

```
PK = Primary Key
FK = Foreign Key
1:N = One-to-Many
0..1 = Zero or One (nullable FK)
```

---

## Cross-Component Reads

```
discovery READS FROM:
  └── jobs (checks if URL already exists before inserting)
  └── audit_logs (INSERT discovery events)
```
