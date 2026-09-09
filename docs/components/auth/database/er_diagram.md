# Auth — ER Diagram

Entity-Relationship diagram for tables owned by the auth component (4 tables).

---

## Diagram

```
┌─────────────────┐
│      users       │
├─────────────────┤
│ PK id       UUID │
│    email    TEXT │
│    password_... │
│    name     TEXT │
│    created_at   │
│    updated_at   │
└────────┬────────┘
         │
         │ 1:N
         ▼
┌─────────────────┐      ┌─────────────────────┐      ┌──────────────────┐
│    api_keys     │      │    settings         │      │  user_profiles   │
├─────────────────┤      ├─────────────────────┤      ├──────────────────┤
│ PK id       UUID │      │FK user_id      UUID │      │PK id        UUID │
│ FK user_id  UUID │      │    key         TEXT │      │FK user_id   UUID │
│    key_hash     │      │    value       JSONB│      │   phone      TEXT│
│    name         │      │    created_at      │      │   linkedin_  TEXT│
│    prefix       │      │    updated_at      │      │    url            │
│    last_used_at │      │PK (user_id, key)    │      │   github_url TEXT│
│    expires_at   │      └─────────────────────┘      │   website_   TEXT│
│    created_at   │                                   │    url            │
└─────────────────┘                                   │   address    TEXT│
                                                      │   city       TEXT│
                                                      │   state      TEXT│
                                                      │   country    TEXT│
                                                      │   postal_    TEXT│
                                                      │    code           │
                                                      │   date_of_   DATE│
                                                      │    birth          │
                                                      │   gender     TEXT│
                                                      │   ethnicity  TEXT│
                                                      │   veteran_   TEXT│
                                                      │    status         │
                                                      │   disability TEXT│
                                                      │    _status        │
                                                      │   work_      TEXT│
                                                      │    authorization  │
                                                      │   custom_ JSONB │
                                                      │    fields         │
                                                      │   created_at     │
                                                      │   updated_at     │
                                                      └──────────────────┘
```

---

## Legend

```
PK = Primary Key
FK = Foreign Key
1:1 = One-to-One
1:N = One-to-Many
```

---

## Cross-Component Reads

```
auth READS FROM:
  └── settings (creates defaults on user registration)
  └── audit_logs (logs auth events)

USED BY:
  └── core_engine (reads user_profiles for field fallback)
  └── backend_api (exposes user_profiles CRUD)
```
