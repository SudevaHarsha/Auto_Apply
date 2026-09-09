# Backend API — API Contract (Source of Truth)

> **This is the source of truth for all HTTP endpoints.** All other components reference this file.
> **Canonical source:** This file IS the canonical source.
> **Base URL:** `http://localhost:8000/api`
> **Format:** JSON (`Content-Type: application/json`)

---

## Authentication

Every request (except `/auth/register`, `/auth/login`, `/health`) requires:

```
Authorization: Bearer <access_token>
```

After JWT validation, PostgreSQL RLS context is set:

```sql
SET LOCAL app.user_id = '<uuid-from-jwt>';
```

---

## Error Response Format

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Human-readable description",
    "details": {},
    "request_id": "req_abc123",
    "timestamp": "2026-08-23T12:00:00Z"
  }
}
```

---

## Rate Limiting

| Endpoint Family | Limit | Window |
|----------------|-------|--------|
| POST /auth/login | 5 requests | 1 minute |
| POST /auth/register | 3 requests | 5 minutes |
| POST /auth/refresh | 10 requests | 1 minute |
| All other endpoints | 100 requests | 1 minute |

Rate limit headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

---

## Pagination

Cursor-based for all list endpoints:

```
GET /api/jobs?limit=20&cursor=<uuid>&status=discovered
```

Response:
```json
{
  "data": [...],
  "pagination": {
    "next_cursor": "uuid|null",
    "has_more": true,
    "total": 142
  }
}
```

| Parameter | Default | Max |
|-----------|---------|-----|
| `limit` | 20 | 100 |
| `cursor` | null | — |
| `sort` | created_at | — |
| `order` | desc | asc/desc |

---

## Complete Endpoint Registry

### Auth (§7)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /auth/register | No | Create account |
| POST | /auth/login | No | Issue JWT pair |
| POST | /auth/refresh | No | Refresh access token |
| GET | /auth/me | Yes | Current user profile |

### Profiles (§8)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /profiles/upload | Yes | Upload resume PDF |
| GET | /profiles | Yes | List all profiles |
| GET | /profiles/current | Yes | Active profile |
| PUT | /profiles/{id} | Yes | Update JSONResume |
| POST | /profiles/{id}/analyze | Yes | Trigger scoring |

### Jobs (§9)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /jobs | Yes | List jobs (filterable) |
| GET | /jobs/{id} | Yes | Single job detail |
| POST | /jobs/manual | Yes | Add job URL manually |
| POST | /jobs/{id}/score | Yes | Score a job |
| POST | /jobs/{id}/approve | Yes | Approve job |
| POST | /jobs/{id}/reject | Yes | Reject job |
| DELETE | /jobs/{id} | Yes | Remove job |

### Applications (§10)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /applications/ready | Yes* | Queued packages (Extension) |
| GET | /applications/{id} | Yes* | Single package (Extension) |
| POST | /applications/{id}/submit | Yes* | Mark as submitted (Extension) |
| POST | /applications/{id}/fill-details | Yes* | Record per-field fill audit (Extension) |

### Extensions (§11)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /extensions/{id}/fill | Yes* | Start filling form (Extension) |
| POST | /extensions/{id}/fill-unmapped | Yes* | LLM values for unmapped fields (Extension) |
| POST | /extensions/{id}/screenshot | Yes* | Capture proof (Extension) |
| POST | /extensions/{id}/submit | Yes* | Confirm submission (Extension) |

### LLM Providers (§12)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /llm/providers | Yes | List user's providers |
| POST | /llm/providers | Yes | Add provider |
| DELETE | /llm/providers/{id} | Yes | Remove provider |
| POST | /llm/test | Yes | Test provider connection |

### Telegram (§13)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /telegram/connect | Yes | Validate + start bot |
| DELETE | /telegram/disconnect | Yes | Stop bot |
| GET | /telegram/status | Yes | Bot health |
| GET | /telegram/groups | Yes | Subscribed groups |

### Discord (§14)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /discord/connect | Yes | Validate + start bot |
| DELETE | /discord/disconnect | Yes | Stop bot |
| GET | /discord/status | Yes | Bot health |
| GET | /discord/servers | Yes | Subscribed servers |

### Checkpoints (§15)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /checkpoints/pending | Yes | Paused jobs |
| POST | /checkpoints/{id}/resume | Yes | Continue pipeline |

### Pipeline (§16)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /pipeline/status | Yes | Current pipeline state |
| POST | /pipeline/{id}/start | Yes | Start pipeline for job |

### Settings (§17)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /settings | Yes | User preferences |
| PUT | /settings | Yes | Update preferences |

### User Profiles (§23)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /user-profiles | Yes | Get supplemental personal info |
| PUT | /user-profiles | Yes | Update supplemental personal info |

> `user_profiles` stores phone, social URLs, DOB, address — used as fallback when resume is missing fields.

### Audit Logs (§18)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /audit | Yes | Audit log entries |
| GET | /audit/{id} | Yes | Single audit entry |

### Error Logs (§19)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /errors | Yes | Error log entries |
| GET | /errors/{id} | Yes | Single error entry |

### Evidence (§20)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /evidence | Yes* | Upload evidence record |
| GET | /evidence/{id} | Yes* | Get evidence record |

### Webhooks (§21)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /webhooks/telegram/message | Internal | Telegram message received |
| POST | /webhooks/discord/message | Internal | Discord message received |

### Health (§22)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /health | No | Service health check |

> `Yes*` = JWT required, but Extension uses a dedicated API key for server-to-server calls.

---

## Status Enum Reference

### jobs.status

```
discovered → scored → approved → applying → applied
                   ↘ rejected
                   ↘ skipped
                   ↘ failed
```

### applications.status

```
created → filling → filled → submitted
                        ↘ skipped (fill blocked; skip_reason set)
                        ↘ failed
```

### pipeline_runs.status

```
running → completed
       ↘ failed
       ↘ paused
```

### telegram_connections.status

```
connected ↔ disconnected
         ↘ error
```

### discord_connections.status

```
active ↔ inactive
      ↘ error
```

---

## Audit Action Reference

```
user_created (legacy alias), user_registered, user_logged_in, user_deleted
profile_uploaded, profile_scored
job_discovered, job_extracted, job_freshness_changed, job_scored, job_approved, job_rejected
application_created, application_filled, application_fill_details, application_submitted, application_skipped, application_failed
pipeline_started, pipeline_completed, pipeline_failed, pipeline_paused, pipeline_resumed
llm_provider_added, llm_provider_removed, llm_provider_failed, llm_fill_request, all_providers_exhausted
extension_connected, extension_disconnected
telegram_connected, telegram_disconnected
discord_connected, discord_disconnected
user_profile_created, user_profile_updated
checkpoint_created, checkpoint_resumed
settings_updated
error_logged
```

---

## Evidence Type Reference

| Type | Captured By | When | Storage |
|------|------------|------|---------|
| screenshot | Extension | After submit | `/data/evidence/{user_id}/{app_id}/screenshot.png` |
| pdf | Extension | After submit | `/data/evidence/{user_id}/{app_id}/application.pdf` |
| dom_snapshot | Extension | After fill | `/data/evidence/{user_id}/{app_id}/dom_snapshot.json` |
| profile_diff | core_engine | After optimization | JSONB in evidence.metadata |
| jd_raw | core_engine | After extraction | JSONB in evidence.metadata |
| message_raw | discovery | On ingestion | JSONB in evidence.metadata |

---

## Component-to-Endpoint Mapping

| Component | Consumes Endpoints |
|-----------|-------------------|
| Frontend (Next.js) | All /api/* endpoints (via browser) |
| Chrome Extension | /api/applications/ready, /api/applications/{id}/fill-details, /api/extensions/*, /api/evidence |
| MCP Engine | /api/profiles/*, /api/jobs/*, /api/applications/*, /api/llm/*, /api/checkpoints/* |
| Chat Interface | /api/jobs/*, /api/pipeline/*, /api/settings, /api/telegram/*, /api/discord/* |
| Discovery | /api/webhooks/telegram/message (internal) |
| Discord Adapter | /api/webhooks/discord/message (internal) |
| Core Engine | Internal function calls (not HTTP) |
| LLM Router | Internal function calls (not HTTP) |
| Observability | Internal triggers (not HTTP) |
| Checkpointing | Internal triggers (not HTTP) |
