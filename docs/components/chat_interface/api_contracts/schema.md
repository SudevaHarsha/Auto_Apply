# Chat Interface — API Contract

> **Consumes:** Multiple Backend API endpoints via Bot Mode (regex) and Agent Mode (LLM tool calls)
> **Shared between:** Web UI and Discord (single component with mode router)
> **Canonical source:** `docs/api_contracts/schema.md` §9, §12, §15, §16, §17

---

## Mode 1: Bot Mode (Zero Token Cost)

All commands are regex-matched. No LLM involved.

| Command | Pattern | HTTP Method + Endpoint |
|---------|---------|----------------------|
| Show jobs | `/show\s+jobs/i` | GET /api/jobs |
| Show discovered | `/show\s+discovered/i` | GET /api/jobs?status=discovered |
| Show approved | `/show\s+approved/i` | GET /api/jobs?status=approved |
| Show rejected | `/show\s+rejected/i` | GET /api/jobs?status=rejected |
| Score job | `/score\s+(?:job\s+)?([a-f0-9-]+)/i` | POST /api/jobs/{id}/score |
| Approve job | `/approve\s+(?:job\s+)?([a-f0-9-]+)/i` | POST /api/jobs/{id}/approve |
| Reject job | `/reject\s+(?:job\s+)?([a-f0-9-]+)/i` | POST /api/jobs/{id}/reject |
| Run pipeline | `/run\s+(?:pipeline\s+)?([a-f0-9-]+)/i` | POST /api/pipeline/{id}/start |
| Resume pipeline | `/resume\s+([a-f0-9-]+)/i` | POST /api/checkpoints/{id}/resume |
| Show providers | `/show\s+providers/i` | GET /api/llm/providers |
| Show status | `/status/i` | GET /api/pipeline/status |
| Help | `/help/i` | (local response) |
| Switch to bot | `/mode bot/i` | (local setting) |
| Switch to agent | `/mode agent/i` | (local setting) |

---

## Mode 2: Agent Mode (Flexible, Token Cost)

LLM decides which tools to call. Tools map to Backend API endpoints.

| Tool Name | HTTP Method + Endpoint |
|-----------|----------------------|
| `search_jobs` | GET /api/jobs |
| `analyze_match` | POST /api/jobs/{id}/score |
| `approve_job` | POST /api/jobs/{id}/approve |
| `reject_job` | POST /api/jobs/{id}/reject |
| `get_package` | GET /api/applications/{application_id} |
| `list_providers` | GET /api/llm/providers |
| `resume_pipeline` | POST /api/checkpoints/{checkpoint_id}/resume |

---

## Endpoint Contracts (Shared across both modes)

### GET /api/jobs

**Query Parameters:**
| Param | Type | Description |
|-------|------|-------------|
| `status` | string | Filter: discovered, scored, approved, applying, applied, rejected, skipped, failed |
| `platform` | string | Filter: greenhouse, lever, linkedin, indeed, workday, generic |
| `source` | string | Filter: telegram, discord, manual |
| `limit` | int | Default 20, max 100 |
| `cursor` | uuid | Pagination cursor |

**Response 200:**
```json
{
  "data": [
    {
      "id": "uuid",
      "title": "string",
      "company": "string",
      "url": "string",
      "platform": "string",
      "source": "string",
      "status": "string",
      "score": "integer|null",
      "raw_message": "string",
      "created_at": "iso8601",
      "updated_at": "iso8601"
    }
  ],
  "pagination": { "next_cursor": "uuid|null", "has_more": "boolean", "total": "integer" }
}
```

---

### POST /api/jobs/{id}/score

**Response 202:**
```json
{
  "status": "scoring",
  "job_id": "uuid",
  "message": "Scoring initiated"
}
```

**Side effects:**
- Calls scoring engine (hiring-agent-main evaluator.py)
- UPDATE `jobs.status = scored`, `jobs.score = <calculated>`
- Logs `job_scored` to `audit_logs`

**Error codes:**
- `JOB_NOT_FOUND` (404)
- `JOB_ALREADY_SCORED` (409)
- `PROFILE_NO_ACTIVE` (404) — no active profile for user

---

### POST /api/jobs/{id}/approve

**Response 200:**
```json
{
  "id": "uuid",
  "status": "approved",
  "updated_at": "iso8601"
}
```

**Side effects:**
- UPDATE `jobs.status = approved`
- Logs `job_approved` to `audit_logs`

---

### POST /api/jobs/{id}/reject

**Request (optional):**
```json
{
  "reason": "string (optional)"
}
```

**Response 200:**
```json
{
  "id": "uuid",
  "status": "rejected",
  "updated_at": "iso8601"
}
```

**Side effects:**
- UPDATE `jobs.status = rejected`
- Logs `job_rejected` to `audit_logs`

---

### POST /api/pipeline/{id}/start

**Request (optional):**
```json
{
  "steps": ["jd_extraction", "rubric_generation", "scoring", "optimization", "package_generation"]
}
```

**Response 202:**
```json
{
  "pipeline_run_id": "uuid",
  "job_id": "uuid",
  "status": "running",
  "steps": ["jd_extraction", "rubric_generation", "scoring", "optimization", "package_generation"],
  "message": "Pipeline started"
}
```

**Step enum:**
```
jd_extraction → rubric_generation → scoring → optimization → package_generation
```

**Side effects:**
- INSERT into `pipeline_runs` with `status = running`
- Executes steps sequentially
- On failure: saves checkpoint, UPDATE `pipeline_runs.status = failed`
- On success: UPDATE `pipeline_runs.status = completed`
- Logs `pipeline_started`, `pipeline_completed` or `pipeline_failed` to `audit_logs`

---

### POST /api/checkpoints/{id}/resume

**Response 200:**
```json
{
  "status": "resumed",
  "checkpoint_id": "uuid",
  "step": "string",
  "message": "Pipeline resumed from scoring step"
}
```

**Side effects:**
- Skips completed steps, restarts from saved step
- UPDATE `pipeline_runs.status = running`
- Logs `pipeline_resumed` to `audit_logs`

**Error codes:**
- `CHECKPOINT_NOT_FOUND` (404)
- `CHECKPOINT_ALREADY_RESUMED` (409)

---

### GET /api/llm/providers

**Response 200:**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "string",
      "base_url": "string",
      "model": "string",
      "is_active": "boolean",
      "priority": "integer",
      "created_at": "iso8601"
    }
  ]
}
```

**Note:** `api_key` is never returned.

---

### GET /api/pipeline/status

**Response 200:**
```json
{
  "active_runs": "integer",
  "paused_runs": "integer",
  "recent_completions": [
    {
      "id": "uuid",
      "job_title": "string",
      "status": "running|completed|failed|paused",
      "steps_run": ["string"],
      "total_time_ms": "integer",
      "completed_at": "iso8601|null"
    }
  ]
}
```

---

### GET /api/settings

**Response 200:**
```json
{
  "chat_mode": "bot|agent",
  "theme": "dark|light",
  "auto_approve_threshold": "integer",
  "notifications_enabled": "boolean",
  "llm_chain": ["string"]
}
```

---

### PUT /api/settings

**Request:**
```json
{
  "chat_mode": "bot|agent",
  "theme": "dark|light",
  "auto_approve_threshold": "integer",
  "notifications_enabled": "boolean",
  "llm_chain": ["string"]
}
```

**Response 200:** Full settings object with `updated_at`.

**Valid settings keys:**
| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `chat_mode` | string | "bot" | "bot" or "agent" |
| `theme` | string | "dark" | "dark" or "light" |
| `auto_approve_threshold` | int | 80 | Score threshold for auto-approve |
| `notifications_enabled` | bool | true | Enable desktop notifications |
| `llm_chain` | string[] | [4 providers] | Ordered list of LLM providers to try |

---

## Mode Switching

| Mode | Behavior |
|------|----------|
| `/mode bot` | All future messages parsed with regex. Zero token cost. Instant responses. |
| `/mode agent` | All future messages sent to LLM. Token cost per message. Flexible natural language. |

**Storage:**
- Web UI: stored in `settings` table (`chat_mode` key)
- Discord: stored in `discord_connections` table (`chat_mode` column)

---

## Response Formats

**Web UI:** React card JSON
```json
{
  "type": "job_list|job_score|error|text",
  "title": "string",
  "jobs": [],
  "text": "string"
}
```

**Discord:** Embed card (adapter converts to Discord embed format)

---

## Audit Actions

| Endpoint | Audit Action | Resource Type |
|----------|-------------|---------------|
| POST /jobs/{id}/score | `job_scored` | job |
| POST /jobs/{id}/approve | `job_approved` | job |
| POST /jobs/{id}/reject | `job_rejected` | job |
| POST /pipeline/{id}/start | `pipeline_started` | pipeline_run |
| POST /checkpoints/{id}/resume | `pipeline_resumed` | checkpoint |
| PUT /settings | `settings_updated` | settings |
