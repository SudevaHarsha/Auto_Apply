# MCP Engine — API Contract

> **Consumes:** 7 Backend API endpoints mapped to MCP tools
> **Auth:** API key (generated in dashboard, stored in env var)
> **Canonical source:** `docs/api_contracts/schema.md` §8, §9, §10, §12, §15

---

## Tool-to-Endpoint Mapping

| MCP Tool | HTTP Endpoint | Method |
|----------|--------------|--------|
| `upload_resume` | POST /api/profiles/upload | POST |
| `search_jobs` | GET /api/jobs | GET |
| `analyze_match` | POST /api/jobs/{id}/score | POST |
| `get_package` | GET /api/applications/{id} | GET |
| `list_providers` | GET /api/llm/providers | GET |
| `get_checkpoint` | GET /api/checkpoints/pending | GET |
| `resume_pipeline` | POST /api/checkpoints/{id}/resume | POST |

---

## Tool 1: upload_resume

**MCP Input:**
```json
{
  "file_path": "string (local path to PDF)"
}
```

**HTTP Call:** `POST /api/profiles/upload` (multipart/form-data)

**HTTP Request:** File uploaded as `file` field.

**HTTP Response 201:**
```json
{
  "id": "uuid",
  "original_pdf_url": "string",
  "json_resume": {
    "basics": { "name": "string", "email": "string", "phone": "string", "summary": "string" },
    "work": [],
    "education": [],
    "skills": []
  },
  "created_at": "iso8601"
}
```

**MCP Output:**
```json
{
  "profile_id": "uuid",
  "sections_extracted": ["basics", "work", "education", "skills"]
}
```

---

## Tool 2: search_jobs

**MCP Input:**
```json
{
  "query": "string (optional)",
  "status": "string (optional: discovered, scored, approved, applying, applied, rejected, skipped, failed)"
}
```

**HTTP Call:** `GET /api/jobs?status={status}`

**HTTP Response 200:**
```json
{
  "data": [
    {
      "id": "uuid",
      "title": "string",
      "company": "string",
      "url": "string",
      "platform": "greenhouse|lever|linkedin|indeed|workday|generic",
      "source": "telegram|discord|manual",
      "status": "discovered|scored|approved|applying|applied|rejected|skipped|failed",
      "score": "integer|null"
    }
  ],
  "pagination": { "next_cursor": "uuid|null", "has_more": "boolean", "total": "integer" }
}
```

**MCP Output:**
```json
{
  "jobs": [
    { "id": "uuid", "title": "string", "url": "string", "platform": "string" }
  ]
}
```

---

## Tool 3: analyze_match

**MCP Input:**
```json
{
  "job_id": "uuid (required)"
}
```

**HTTP Call:** `POST /api/jobs/{job_id}/score`

**HTTP Response 202:**
```json
{
  "status": "scoring",
  "job_id": "uuid",
  "message": "Scoring initiated"
}
```

**MCP Output:**
```json
{
  "score": "integer (0-100)",
  "strengths": ["string"],
  "weaknesses": ["string"]
}
```

**Note:** MCP tool may poll `GET /api/jobs/{id}` until `status = scored` to return final score.

---

## Tool 4: get_package

**MCP Input:**
```json
{
  "application_id": "uuid (required)"
}
```

**HTTP Call:** `GET /api/applications/{application_id}`

**HTTP Response 200:**
```json
{
  "id": "uuid",
  "job": { "title": "string", "company": "string", "url": "string", "platform": "string" },
  "optimized_resume": {},
  "cover_letter": "string",
  "pdf_url": "string",
  "field_mappings": {},
  "status": "created|filling|filled|submitted|skipped|failed"
}
```

**MCP Output:**
```json
{
  "pdf_url": "string",
  "cover_letter": "string",
  "field_mappings": {}
}
```

---

## Tool 5: list_providers

**MCP Input:** (none)

**HTTP Call:** `GET /api/llm/providers`

**HTTP Response 200:**
```json
{
  "data": [
    {
      "id": "uuid",
      "name": "string",
      "base_url": "string",
      "model": "string",
      "is_active": "boolean",
      "priority": "integer"
    }
  ]
}
```

**MCP Output:**
```json
{
  "providers": [
    { "name": "string", "status": "active|inactive|error" }
  ]
}
```

---

## Tool 6: get_checkpoint

**MCP Input:** (none)

**HTTP Call:** `GET /api/checkpoints/pending`

**HTTP Response 200:**
```json
{
  "data": [
    {
      "id": "uuid",
      "job": { "id": "uuid", "title": "string", "company": "string" },
      "step": "jd_extraction|rubric_generation|scoring|optimization|package_generation",
      "error_message": "string",
      "created_at": "iso8601"
    }
  ]
}
```

**MCP Output:**
```json
{
  "checkpoints": [
    { "job_id": "uuid", "step": "string", "state": "string" }
  ]
}
```

---

## Tool 7: resume_pipeline

**MCP Input:**
```json
{
  "checkpoint_id": "uuid (required)"
}
```

**HTTP Call:** `POST /api/checkpoints/{checkpoint_id}/resume`

**HTTP Response 200:**
```json
{
  "status": "resumed",
  "checkpoint_id": "uuid",
  "step": "string",
  "message": "Pipeline resumed from scoring step"
}
```

**MCP Output:**
```json
{
  "status": "resumed",
  "next_step": "string"
}
```

---

## Agent Interaction Flow

```
User (in OpenCode): "/plan run job https://greenhouse..."

Agent:
  1. Calls search_jobs (find the job)
  2. Calls analyze_match (score it)
  3. Shows score to user
  4. User says "go ahead"
  5. Calls resume_pipeline (starts pipeline)
  6. Calls get_package (gets application package)
  7. Shows package to user
  8. User clicks Submit in extension
```

---

## Audit Actions

| Tool | Audit Action | Resource Type |
|------|-------------|---------------|
| upload_resume | `profile_uploaded` | profile |
| analyze_match | `profile_scored` + `job_scored` | profile + job |
| resume_pipeline | `pipeline_resumed` | checkpoint |
