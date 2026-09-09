# Security Boundaries

Trust zones and data isolation across the system.

---

## Trust Zones

```
┌─────────────────────────────────────────────────────────────────┐
│                                                                  │
│  ZONE 1: TRUSTED (Server-Side)                                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │  │
│  │  │  Core Engine  │  │  PostgreSQL  │  │  API Key Store │   │  │
│  │  │  (all LLM    │  │  (RLS        │  │  (AES-256      │   │  │
│  │  │   calls)     │  │   enforced)  │  │   encrypted)   │   │  │
│  │  └──────────────┘  └──────────────┘  └────────────────┘   │  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │  │
│  │  │  Core Engine  │  │  Evidence    │  │  Audit Logs    │   │  │
│  │  │  (pipeline   │  │  Storage     │  │  (append-only, │   │  │
│  │  │   runner)    │  │  (screenshots│  │   immutable)   │   │  │
│  │  │              │  │   PDFs)      │  │                │   │  │
│  │  └──────────────┘  └──────────────┘  └────────────────┘   │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ZONE 2: SEMI-TRUSTED (User's Browser)                          │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │  │
│  │  │  Chrome      │  │  User's      │  │  Telegram App  │   │  │
│  │  │  Extension   │  │  Login       │  │  (user's own   │   │  │
│  │  │  (fills      │  │  Sessions    │  │   account)     │   │  │
│  │  │   forms)     │  │  (ATS sites) │  │                │   │  │
│  │  └──────────────┘  └──────────────┘  └────────────────┘   │  │
│  │                                                            │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ZONE 3: UNTRUSTED (External)                                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │                                                            │  │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │  │
│  │  │  LLM         │  │  ATS         │  │  Career Pages  │   │  │
│  │  │  Providers   │  │  Websites    │  │  (HTML to      │   │  │
│  │  │  (Gemini,    │  │  (Greenhouse,│  │   scrape)      │   │  │
│  │  │   Groq, etc) │  │   LinkedIn)  │  │                │   │  │
│  │  └──────────────┘  └──────────────┘  └────────────────┘   │  │
│  │                                                            │  │
│  │  ┌──────────────┐                                            │  │
│  │  │  Telegram    │                                            │  │
│  │  │  Bot API     │                                            │  │
│  │  └──────────────┘                                            │  │
│  │                                                              │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Data Isolation (Multi-Tenancy)

```
PostgreSQL Row-Level Security (RLS) via app_user role + SET LOCAL

Database Roles:
  postgres (superuser)
  ├── Runs migrations only
  ├── Creates tables, indexes, policies
  └── NEVER used by FastAPI at runtime

  app_user (non-superuser, non-owner)
  ├── CONNECT, SELECT, INSERT, UPDATE, DELETE
  ├── Does NOT own any tables
  ├── RLS applies (non-owner + non-superuser)
  └── FastAPI connects as this role

FORCE ROW LEVEL SECURITY:
  ALTER TABLE <table> FORCE ROW LEVEL SECURITY;
  ├── Applied to all 19 tables
  ├── Ensures RLS applies even if role becomes table owner
  └── Defense in depth against migration grants

Per-Transaction SET LOCAL:
  async def get_db_with_rls(user):
      async with session_factory() as session:
          await session.execute(
              text("SET LOCAL app.user_id = :uid"),
              {"uid": str(user.id)}
          )
          yield session

  ├── SET LOCAL scoped to this transaction
  ├── Auto-clears at commit/rollback
  └── No leakage between requests

Why NOT event.listens_for("connect"):
  SQLAlchemy pools connections. "connect" fires once per
  pool checkout, not per request.

  Request 1 (user A): SET LOCAL user_id = A
  Connection returned to pool
  Request 2 (user B): reuses same connection
  → user_id is still A from last SET LOCAL
  → user B sees user A's data (SECURITY BREACH)

  SET LOCAL auto-clears at transaction end, but
  pool checkout is not a transaction boundary.

Result:
  FastAPI connects as app_user (non-superuser)
  RLS enforced via policies + FORCE ROW LEVEL SECURITY
  SET LOCAL scoped per-request via FastAPI dependency

  SELECT * FROM jobs;
  → Only returns jobs WHERE user_id = current user

  Even if handler forgets WHERE user_id =:
  → RLS policy filters automatically
```

### Login lookup carve-out (D10)

At login the caller has **no identity yet**, so `app_user` cannot `SELECT users WHERE email=…`
under RLS — the policy filters by `id = GUC`, and the GUC is unset. The **only** path is a
narrow SECURITY DEFINER function:

```
auth_user_by_email(email text)  -- owned by postgres (migration-time)
  → RETURNS TABLE (id, email, password_hash, name)
  → EXACT-match, single row, STABLE
  → EXECUTE granted to app_user only
```

`postgres` remains unused by FastAPI at runtime; the function runs as its creator for the single
lookup only. This is a **deliberate, documented carve-out** — see `plans/steps/S3-auth.md` D10.

---

## API Key Security

```
User provides API key
        │
        ▼
┌──────────────────┐
│ FastAPI receives  │
│ key over HTTPS    │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Encrypt with     │
│ AES-256 using    │
│ server env key   │
│                  │
│ KEY: ████████    │
│ (env variable)   │
└────────┬─────────┘
         │
         ▼
┌──────────────────┐
│ Store encrypted  │
│ in PostgreSQL    │
│                  │
│ llm_providers:   │
│ api_key_encrypted│
│ aGVsbG8gd29ybGQ= │
└────────┬─────────┘
         │
         │ When LLM call needed:
         ▼
┌──────────────────┐
│ Decrypt in memory│
│ Use for API call │
│ Discard after    │
│                  │
│ Never logged     │
│ Never stored     │
│ in plaintext     │
└──────────────────┘
```

> This flow is the **`llm_providers`** path (reversible provider secrets, AES-256).

### API-key hashes vs provider secrets (D12)

`api_keys.key_hash` is **not** AES-256-encrypted — it is a **SHA-256 hash** (one-way, unusable
for round-trip recovery). The "API Key Store (AES-256 encrypted)" label in the trust-zone diagram
applies **only** to `llm_providers.api_key_encrypted` (decrypted in memory, never persisted plain).

```
THING                            STORAGE                          REVERSIBLE?
──────────────────────────────────────────────────────────────────────────
llm_providers.api_key_encrypted  AES-256 (server env key)          Yes (in-memory only)
api_keys.key_hash                SHA-256 hash + prefix + name     No (one-way)
```

- `api_keys` stores only `key_hash`, `prefix`, `name`, `last_used_at`, `expires_at`.
- The plaintext API-key secret is returned **exactly once** at creation, then discarded.

---

## Extension Security Rules

```
Chrome Extension
├── CANNOT:
│   ├── Auto-submit forms (user always clicks Submit)
│   ├── Read passwords from browser
│   ├── Access other extensions' data
│   ├── Make requests from page context (only via service worker)
│   └── Inject visible UI elements into pages
│
├── CAN:
│   ├── Read current page DOM (content script)
│   ├── Fill form fields with user's profile data
│   ├── Capture screenshot of current tab
│   ├── Communicate with backend via REST (service worker)
│   └── Store minimal state in chrome.storage
│
└── Data flow:
    Backend ──REST──▶ Extension ──DOM──▶ ATS Website
                  (profile data)    (form fields)
    
    No data sent to third parties from extension.
    All API calls go through backend, not page scripts.
```
