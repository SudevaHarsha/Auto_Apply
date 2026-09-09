# Chat Interface — Schema

Chat Interface is stateless. It owns no database tables.

---

## Tables Owned

```
(none)
```

All data lives in Backend API tables. Chat Interface reads from:
- `discord_connections` (chat_mode for Discord users)
- `settings` (chat_mode for Web UI users)
- `jobs` (list jobs, check status)
- `applications` (get package)
- `llm_providers` (list providers)
- `checkpoints` (get pending)

All writes go through Backend API endpoints.

---

## Why Stateless

```
Chat Interface is a processing layer, not a storage layer.

User message → Chat Interface → Backend API → Database
                                    ↑
                          (all writes happen here)

Chat Interface only:
  1. Reads chat_mode to decide processing mode
  2. Processes message (regex or LLM)
  3. Calls Backend API endpoints
  4. Formats response for platform
```

---

## Tables It Depends On

```
TABLE               DEPENDENCY          WHY
────────────────────────────────────────────────────────────────
discord_connections  reads chat_mode     Determine Bot vs Agent mode
settings            reads chat_mode     Determine Bot vs Agent mode
jobs                reads/writes via API Score, approve, reject
applications        reads via API       Get package
llm_providers       reads via API       List providers
checkpoints         reads via API       Get pending
```
