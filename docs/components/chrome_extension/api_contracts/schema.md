# Chrome Extension — API Contract

> **Consumes:** `GET /api/applications/ready`, `GET /api/applications/{id}`, `POST /api/applications/{id}/submit`, `POST /api/applications/{id}/fill-details`, `POST /api/extensions/{id}/fill`, `POST /api/extensions/{id}/fill-unmapped`, `POST /api/extensions/{id}/screenshot`, `POST /api/extensions/{id}/submit`, `POST /api/evidence`
> **Auth:** Dedicated Extension API key (not user JWT) for server-to-server calls
> **Canonical source:** `docs/api_contracts/schema.md` §10, §11, §20

---

## Endpoints Consumed

### GET /api/applications/ready

Poll for queued application packages ready to fill.

**Response 200:**
```json
{
  "data": [
    {
      "id": "uuid (application_id)",
      "job": {
        "id": "uuid",
        "title": "string",
        "company": "string",
        "url": "string",
        "platform": "greenhouse|lever|linkedin|indeed|workday|generic"
      },
      "optimized_resume": {
        "skills": ["string"],
        "summary": "string"
      },
      "cover_letter": "string",
      "pdf_url": "string (/data/evidence/{user_id}/{app_id}/application.pdf)",
      "field_mappings": {
        "first_name": "string",
        "last_name": "string",
        "email": "string",
        "phone": "string",
        "resume_url": "string",
        "cover_letter": "string",
        "linkedin_url": "string",
        "github_url": "string",
        "website": "string",
        "years_experience": "string",
        "desired_salary": "string",
        "work_authorization": "string",
        "skills": "string",
        "education": "string",
        "location": "string",
        "custom_fields": {}
      },
      "status": "created",
      "created_at": "iso8601"
    }
  ]
}
```

---

### GET /api/applications/{id}

Get a single application package.

**Response 200:**
```json
{
  "id": "uuid",
  "job": { "id": "uuid", "title": "string", "company": "string", "url": "string", "platform": "string" },
  "profile": { "id": "uuid" },
  "optimized_resume": {},
  "cover_letter": "string",
  "pdf_url": "string",
  "field_mappings": {},
  "status": "created|filling|filled|submitted|skipped|failed",
  "screenshot_url": "string|null",
  "filled_at": "iso8601|null",
  "submitted_at": "iso8601|null",
  "created_at": "iso8601"
}
```

**Error codes:**
- `APPLICATION_NOT_FOUND` (404)
- `APPLICATION_NOT_READY` (409) — package not yet generated

---

### POST /api/extensions/{id}/fill-unmapped

Request LLM-generated values for form fields that didn't match `field_mappings`.

**Request:**
```json
{
  "application_id": "uuid",
  "fields": [
    "Why do you want to work at Stripe?",
    "Describe your leadership experience"
  ],
  "jd_context": "string (optional — JD summary for context)"
}
```

**Response 200:**
```json
{
  "values": {
    "Why do you want to work at Stripe?": "I'm drawn to Stripe's mission to increase GDP...",
    "Describe your leadership experience": "At my previous role, I led a team of 5..."
  }
}
```

**Side effects:**
- Backend calls LLM via provider chain (Gemini → Ollama → Groq → OpenRouter)
- LLM prompt includes: field labels, JD context, user profile summary
- Logs `llm_fill_request` to `audit_logs`
- Token usage tracked in `provider_usage`

**Error codes:**
- `APPLICATION_NOT_FOUND` (404)
- `LLM_PROVIDERS_EXHAUSTED` (503) — all free-tier providers failed

---

### POST /api/extensions/{id}/fill

Tell the Extension to start filling a form.

**Request:**
```json
{
  "field_mappings": {
    "first_name": "string",
    "last_name": "string",
    "email": "string",
    "phone": "string",
    "resume_url": "string",
    "cover_letter": "string",
    "linkedin_url": "string",
    "github_url": "string",
    "website": "string",
    "years_experience": "string",
    "desired_salary": "string",
    "work_authorization": "string",
    "skills": "string",
    "education": "string",
    "location": "string",
    "custom_fields": {}
  },
  "application_id": "uuid"
}
```

**Response 200:**
```json
{
  "status": "filling",
  "message": "Form filling initiated"
}
```

**Side effects:**
- UPDATE `applications.status = filling`
- Extension fills fields with human-like pacing (300-800ms per field)
- Extension captures DOM snapshot after filling

**Error codes:**
- `APPLICATION_ALREADY_FILLED` (409)
- `EXTENSION_INVALID_STATE` (409)

---

### POST /api/applications/{id}/fill-details

Record the per-field fill audit trail from the extension.

**Request:**
```json
{
  "fill_details": [
    {
      "label": "First Name",
      "value": "John",
      "filled": true,
      "error": null,
      "required": true,
      "tier": "deterministic"
    },
    {
      "label": "Why do you want to work at Stripe?",
      "value": "I'm drawn to Stripe's mission...",
      "filled": true,
      "error": null,
      "required": true,
      "tier": "llm_fallback"
    },
    {
      "label": "CAPTCHA",
      "value": null,
      "filled": false,
      "error": "requires_human",
      "required": true,
      "tier": "manual"
    }
  ]
}
```

**Response 200:**
```json
{
  "status": "recorded",
  "filled_count": 7,
  "unfilled_count": 1
}
```

**Side effects:**
- UPDATE `applications.fill_details = <provided>`
- If any field has `filled=false` and `error=requires_human`, application stays `filling`
- Logs `application_fill_details` to `audit_logs`

**Error codes:**
- `APPLICATION_NOT_FOUND` (404)

---

### POST /api/extensions/{id}/screenshot

Capture a screenshot of the current page state.

**Request:**
```json
{
  "type": "confirmation",
  "metadata": {
    "url": "string (current page URL)",
    "field_count": 8,
    "filled_count": 8
  }
}
```

**Response 200:**
```json
{
  "evidence_id": "uuid",
  "file_url": "string (/data/evidence/{user_id}/{app_id}/screenshot.png)",
  "type": "screenshot"
}
```

**Side effects:**
- Saves screenshot to `/data/evidence/{user_id}/{app_id}/screenshot.png`
- INSERT into `evidence` table
- Logs `application_filled` to `audit_logs`

---

### POST /api/extensions/{id}/submit

Confirm the application was submitted by the user.

**Request:**
```json
{
  "screenshot_url": "string (/data/evidence/{user_id}/{app_id}/confirmation.png)"
}
```

**Response 200:**
```json
{
  "status": "submitted",
  "message": "Application marked as submitted"
}
```

**Side effects:**
- UPDATE `applications.status = submitted`, `applications.submitted_at`
- UPDATE `jobs.status = applied`
- Saves confirmation screenshot to evidence
- Logs `application_submitted` to `audit_logs`

**Error codes:**
- `APPLICATION_ALREADY_SUBMITTED` (409)

---

### POST /api/evidence

Upload an evidence record.

**Request:** `multipart/form-data`

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `application_id` | uuid | Yes | Link to application |
| `type` | string | Yes | screenshot, pdf, dom_snapshot, profile_diff, jd_raw, message_raw |
| `file` | file | No* | Binary file (required for screenshot/pdf/dom_snapshot) |
| `metadata` | string | No | JSON string of additional metadata |

**Response 201:**
```json
{
  "id": "uuid",
  "application_id": "uuid",
  "type": "screenshot|pdf|dom_snapshot|profile_diff|jd_raw|message_raw",
  "file_url": "string",
  "metadata": {},
  "created_at": "iso8601"
}
```

**Side effects:**
- Saves file to `/data/evidence/{user_id}/{app_id}/{filename}`
- INSERT into `evidence` table
- Logs evidence capture event to `audit_logs`

---

## Fill Sequence (Extension Flow)

```
1. Extension polls GET /api/applications/ready
   (gets field_mappings for each ready application)
2. User clicks [Fill] on a job in the popup
3. Extension scans form fields on the career page
   ├── Tier 1: match fields against field_mappings → fill locally (0 cost)
   └── Tier 2: unmapped fields → POST /api/extensions/{id}/fill-unmapped
              → LLM generates values → fill
4. Extension fills all fields (300-800ms per field, natural events)
5. Extension calls POST /api/applications/{id}/fill-details with per-field audit
6. Extension calls POST /api/extensions/{id}/screenshot (dom_snapshot)
7. User reviews form, solves CAPTCHA manually
8. User manually clicks Submit on the career page
9. Extension calls POST /api/extensions/{id}/submit with confirmation screenshot
10. Backend marks application as submitted
```

---

## Fill Blockers (skip_reason)

When the form can't be filled, the extension reports the blocker:

| skip_reason | Meaning |
|---|---|
| `sso_wall` | Company uses SSO login — form unreachable |
| `captcha_required` | CAPTCHA blocks automated fill |
| `unsupported_platform` | Platform not recognized — manual package |
| `form_not_found` | No application form on the page |
| `salary_mismatch` | JD salary below user minimum |
| `expired` | Posting expired before fill |

---

## Platform Adapters

| Platform | Fill Strategy | Auto-Submit |
|----------|--------------|-------------|
| Greenhouse | Auto-fill all fields | No (user clicks) |
| Lever | Auto-fill all fields | No (user clicks) |
| LinkedIn | Cautious fill (some fields) | No (user clicks) |
| Indeed | Manual package (PDF only) | No (user clicks) |
| Workday | Manual package (PDF only) | No (user clicks) |
| Generic | Best-effort auto-fill | No (user clicks) |

---

## Audit Actions

| Endpoint | Audit Action | Resource Type |
|----------|-------------|---------------|
| POST /extensions/{id}/fill | `application_filled` | application |
| POST /extensions/{id}/screenshot | `application_filled` | application |
| POST /extensions/{id}/submit | `application_submitted` | application |
| POST /evidence | (evidence capture event) | application |
