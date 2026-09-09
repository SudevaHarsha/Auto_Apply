# Chat Interface — Database Scope

Stateless component. Reads from multiple tables, owns none.

---

## Tables Owned

```
(none)
```

Chat Interface is stateless. All data lives in Backend API tables.

---

## Tables Read

```
TABLE                 READ BY                  WHY
─────────────────────────────────────────────────────────────────
discord_connections   chat_interface           read chat_mode for Discord users
settings              chat_interface           read chat_mode for Web UI users
jobs                  chat_interface           list jobs, check status
applications          chat_interface           get package for approved jobs
llm_providers         chat_interface           list providers, check status
checkpoints           chat_interface           get pending checkpoints
user_profiles         chat_interface           notify missing required fields
```

---

## Tables Written (via Backend API)

```
Chat Interface does NOT write directly.
All writes go through Backend API endpoints.

ENDPOINT                          TABLE WRITTEN     TRIGGER
──────────────────────────────────────────────────────────────
POST /api/jobs/{id}/score        jobs              score updated
POST /api/jobs/{id}/approve      jobs              status → approved
POST /api/jobs/{id}/reject       jobs              status → rejected
POST /api/pipeline/{id}/start    pipeline_runs     pipeline started
POST /api/checkpoints/{id}/resume checkpoints       pipeline resumed
```

---

## Data Flow

```
USER MESSAGE ARRIVES
        |
        v
┌───────────────────────────────────────────────────────────────┐
│  READ chat_mode                                               │
│                                                               │
│  Web UI:   SELECT value FROM settings WHERE user_id = ? AND key = 'chat_mode'  │
│  Discord:  SELECT chat_mode FROM discord_connections           │
│            WHERE user_id = ?                                  │
└───────────────────────────────────────────────────────────────┘
        |
        v
┌───────────────────────────────────────────────────────────────┐
│  PROCESS MESSAGE (Bot or Agent Mode)                           │
│                                                               │
│  Bot Mode:   regex parse → API call                           │
│  Agent Mode: LLM parse → tool call → API call                 │
└───────────────────────────────────────────────────────────────┘
        |
        v
┌───────────────────────────────────────────────────────────────┐
│  CALL Backend API                                             │
│                                                               │
│  GET  /api/jobs                    → list jobs                │
│  POST /api/jobs/{id}/score        → score job                │
│  POST /api/jobs/{id}/approve      → approve job              │
│  GET  /api/llm/providers          → list providers           │
│  ... etc                                                       │
└───────────────────────────────────────────────────────────────┘
        |
        v
┌───────────────────────────────────────────────────────────────┐
│  FORMAT RESPONSE                                              │
│                                                               │
│  Web UI:   React card component                               │
│  Discord:  Embed card                                         │
└───────────────────────────────────────────────────────────────┘
```

---

## Read Patterns

### Bot Mode

```
PATTERN                           SQL                          WHEN
─────────────────────────────────────────────────────────────────────
List jobs                         SELECT * FROM jobs           /show jobs
  WHERE user_id = ?                WHERE user_id = ?
  AND status = ?                   AND status = ?

List providers                    SELECT * FROM llm_providers  /show providers
  WHERE user_id = ?                WHERE user_id = ?
```

### Agent Mode

```
PATTERN                           SQL                          WHEN
─────────────────────────────────────────────────────────────────────
Search jobs                       SELECT * FROM jobs           search_jobs tool
  WHERE user_id = ?                WHERE user_id = ?
  AND title ILIKE ?                AND title ILIKE '%query%'

Analyze match                     SELECT * FROM jobs           analyze_match tool
  WHERE id = ?                     WHERE id = ?
  + LLM scoring                   + LLM scoring

Get package                       SELECT * FROM applications   get_package tool
  WHERE id = ?                     WHERE id = ?
```

---

## Relationships

```
chat_interface reads from multiple tables but owns none:

discord_connections ──────> chat_interface reads chat_mode
settings ─────────────────> chat_interface reads chat_mode
jobs ─────────────────────> chat_interface reads/writes via API
applications ─────────────> chat_interface reads via API
llm_providers ────────────> chat_interface reads via API
checkpoints ──────────────> chat_interface reads via API
user_profiles ────────────> chat_interface reads for missing field notification
```
