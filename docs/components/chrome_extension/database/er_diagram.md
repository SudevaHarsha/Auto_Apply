# Chrome Extension — ER Diagram

Entity-Relationship diagram for tables owned by the chrome extension component.

---

## Diagram

```
┌─────────────────┐
│    evidence     │
├─────────────────┤
│PK id       UUID │
│FK application_  │
│    id      UUID │  (NULL for profile_diff, jd_raw, message_raw)
│FK user_id  UUID │
│   type          │  screenshot/pdf/dom_snapshot/profile_diff/jd_raw/message_raw
│   file_url      │
│   metadata JSONB│
│   created_at    │
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
chrome_extension READS FROM:
  └── applications (links evidence to application)
  └── audit_logs (INSERT evidence capture events)

USED BY:
  └── core_engine (reads evidence for status display)
  └── frontend (displays evidence gallery)
```
