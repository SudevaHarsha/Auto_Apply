# API Contracts — AutoApply

> **Canonical source:** This file defines every HTTP endpoint in the AutoApply system. All components (Frontend, Chrome Extension, MCP Engine, Chat Interface) consume these endpoints. Backend API is the single entry point — no component accesses the database directly.

---

## Table of Contents

1. [Base URL & Versioning](#1-base-url--versioning)
2. [Authentication](#2-authentication)
3. [Error Response Format](#3-error-response-format)
4. [Rate Limiting](#4-rate-limiting)
5. [Pagination](#5-pagination)
6. [Endpoint Registry](#6-endpoint-registry)
7. [Auth Endpoints](#7-auth-endpoints)
8. [Profile Endpoints](#8-profile-endpoints)
9. [Job Endpoints](#9-job-endpoints)
10. [Application Endpoints](#10-application-endpoints)
11. [Extension Endpoints](#11-extension-endpoints)
12. [LLM Provider Endpoints](#12-llm-provider-endpoints)
13. [Telegram Endpoints](#13-telegram-endpoints)
14. [Discord Endpoints](#14-discord-endpoints)
15. [Checkpoint Endpoints](#15-checkpoint-endpoints)
16. [Pipeline Endpoints](#16-pipeline-endpoints)
17. [Settings Endpoints](#17-settings-endpoints)
18. [Audit Log Endpoints](#18-audit-log-endpoints)
19. [Error Log Endpoints](#19-error-log-endpoints)
20. [Evidence Endpoints](#20-evidence-endpoints)
21. [Webhook Endpoints](#21-webhook-endpoints)
22. [Health Check](#22-health-check)
23. [User Profile Endpoints](#23-user-profile-endpoints)

---

## 1. Base URL & Versioning

```
Base URL:    http://localhost:8000/api
Versioning:  URL-based (/api/v1/...) — currently unversioned (v0)
Format:      JSON (Content-Type: application/json)
```

All timestamps are ISO 8601 UTC (`2026-08-23T12:00:00Z`). All IDs are UUID v4.

---

## 2. Authentication

### JWT Authentication

Every request (except `/api/auth/register`, `/api/auth/login`, `/api/health`) requires a valid JWT in the `Authorization` header:

```
Authorization: Bearer <access_token>
```

### Token Lifecycle

```
Endpoint              Token Type    Expires
──────────────────────────────────────────────
POST /auth/login      access        15 minutes
POST /auth/login      refresh       7 days
POST /auth/refresh    access        15 minutes (new pair)
```

### Token Payload

```json
{
  "sub": "uuid-of-user",
  "email": "user@example.com",
  "name": "John Doe",
  "iat": 1755993600,
  "exp": 1755994500
}
```

### RLS Context

After JWT validation, the backend sets the PostgreSQL session variable for row-level security:

```sql
SET LOCAL app.user_id = '<uuid-from-jwt>';
```

Every query automatically filters rows by `user_id`. No cross-user data leakage is possible.

---

## 3. Error Response Format

All errors follow a consistent structure:

```json
{
  "error": {
    "code": "JOB_NOT_FOUND",
    "message": "No job found with the given ID",
    "details": {},
    "request_id": "req_abc123",
    "timestamp": "2026-08-23T12:00:00Z"
  }
}
```

### Error Codes

```
CODE                        HTTP STATUS  DESCRIPTION
────────────────────────────────────────────────────────────────
AUTH_INVALID_CREDENTIALS    401          Wrong email/password
AUTH_TOKEN_EXPIRED          401          Access token expired
AUTH_TOKEN_INVALID          401          Malformed or invalid token
AUTH_REFRESH_EXPIRED        401          Refresh token expired
AUTH_USER_EXISTS            409          Email already registered
AUTH_WEAK_PASSWORD          400          Password does not meet requirements

PROFILE_NOT_FOUND           404          No profile with given ID
PROFILE_UPLOAD_FAILED       422          PDF parsing failed
PROFILE_NO_ACTIVE           404          No active profile for user

JOB_NOT_FOUND               404          No job with given ID
JOB_INVALID_URL             422          URL does not point to a job posting
JOB_ALREADY_SCORED          409          Job has already been scored
JOB_INVALID_TRANSITION      409          Status transition not allowed

APPLICATION_NOT_FOUND       404          No application with given ID
APPLICATION_NOT_READY       409          Application package not yet generated
APPLICATION_ALREADY_FILLED  409          Form already filled
APPLICATION_ALREADY_SUBMITTED 409        Already submitted

LLM_PROVIDERS_EXHAUSTED     503          All free-tier LLM providers failed (Tier 2 fill)

PROVIDER_NOT_FOUND          404          No provider with given ID
PROVIDER_TEST_FAILED        422          Provider connection test failed
PROVIDER_DUPLICATE          409          Provider with same name exists

EXTENSION_NOT_FOUND         404          No evidence record with given ID
EXTENSION_INVALID_STATE     409          Extension action not valid in current state

CHECKPOINT_NOT_FOUND        404          No checkpoint with given ID
CHECKPOINT_ALREADY_RESUMED  409          Checkpoint already completed

PIPELINE_NOT_FOUND          404          No pipeline run with given ID
PIPELINE_ALREADY_RUNNING    409          Pipeline already in progress

TELEGRAM_INVALID_TOKEN      422          Bot token validation failed
TELEGRAM_ALREADY_CONNECTED  409          Telegram bot already connected
TELEGRAM_NOT_CONNECTED      409          No active Telegram connection

DISCORD_INVALID_TOKEN       422          Bot token validation failed
DISCORD_ALREADY_CONNECTED   409          Discord bot already connected
DISCORD_NOT_CONNECTED       409          No active Discord connection

SETTINGS_KEY_INVALID        400          Unknown settings key
SETTINGS_VALUE_INVALID      422          Value does not match expected schema

VALIDATION_ERROR            422          Request body failed validation
RATE_LIMITED                429          Too many requests
INTERNAL_ERROR              500          Unexpected server error
```

---

## 4. Rate Limiting

```
Endpoint Family          Limit              Window
─────────────────────────────────────────────────────
POST /auth/login         5 requests         1 minute
POST /auth/register      3 requests         5 minutes
POST /auth/refresh       10 requests        1 minute
All other endpoints      100 requests       1 minute
LLM provider calls       Per-provider limit (configurable)
```

Rate limit headers are included in every response:

```
X-RateLimit-Limit: 100
X-RateLimit-Remaining: 97
X-RateLimit-Reset: 1755993660
```

When rate limited:

```json
{
  "error": {
    "code": "RATE_LIMITED",
    "message": "Too many requests. Try again in 30 seconds.",
    "retry_after": 30
  }
}
```

---

## 5. Pagination

List endpoints support cursor-based pagination:

### Request

```
GET /api/jobs?limit=20&cursor=<uuid>&status=discovered
```

### Response

```json
{
  "data": [...],
  "pagination": {
    "next_cursor": "uuid-of-last-item",
    "has_more": true,
    "total": 142
  }
}
```

| Parameter | Default | Max | Description |
|-----------|---------|-----|-------------|
| `limit`   | 20      | 100 | Items per page |
| `cursor`  | null    | —   | UUID of last item from previous page |
| `sort`    | created_at | — | Sort field |
| `order`   | desc    | asc/desc | Sort direction |

---

## 6. Endpoint Registry

```
METHOD   PATH                              AUTH    DESCRIPTION
─────────────────────────────────────────────────────────────────────────
POST     /auth/register                    No      Create account
POST     /auth/login                       No      Issue JWT pair
POST     /auth/refresh                     No      Refresh access token
POST     /auth/logout                      Yes     Revoke active session
GET      /auth/me                          Yes     Current user profile

POST     /profiles/upload                  Yes     Upload resume PDF
GET      /profiles                         Yes     List all profiles
GET      /profiles/current                 Yes     Active profile
PUT      /profiles/{id}                    Yes     Update JSONResume
POST     /profiles/{id}/analyze            Yes     Trigger scoring

GET      /jobs                             Yes     List jobs (filterable)
GET      /jobs/{id}                        Yes     Single job detail
POST     /jobs/manual                      Yes     Add job URL manually
POST     /jobs/{id}/score                  Yes     Score a job
POST     /jobs/{id}/approve                Yes     Approve job
POST     /jobs/{id}/reject                 Yes     Reject job
DELETE   /jobs/{id}                        Yes     Remove job

GET      /applications/ready               Yes*    Queued packages (Extension)
GET      /applications/{id}                Yes*    Single package (Extension)
POST     /applications/{id}/submit         Yes*    Mark as submitted (Extension)
POST     /applications/{id}/fill-details   Yes*    Record per-field fill audit (Extension)

POST     /extensions/{id}/fill             Yes*    Start filling form (Extension)
POST     /extensions/{id}/fill-unmapped    Yes*    LLM values for unmapped fields (Extension)
POST     /extensions/{id}/screenshot       Yes*    Capture proof (Extension)
POST     /extensions/{id}/submit           Yes*    Confirm submission (Extension)

GET      /llm/providers                    Yes     List user's providers
POST     /llm/providers                    Yes     Add provider
DELETE   /llm/providers/{id}               Yes     Remove provider
POST     /llm/test                         Yes     Test provider connection

POST     /telegram/connect                 Yes     Validate + start bot
DELETE   /telegram/disconnect              Yes     Stop bot
GET      /telegram/status                  Yes     Bot health
GET      /telegram/groups                  Yes     Subscribed groups

POST     /discord/connect                  Yes     Validate + start bot
DELETE   /discord/disconnect               Yes     Stop bot
GET      /discord/status                   Yes     Bot health
GET      /discord/servers                  Yes     Subscribed servers

GET      /checkpoints/pending              Yes     Paused jobs
POST     /checkpoints/{id}/resume          Yes     Continue pipeline

GET      /pipeline/status                  Yes     Current pipeline state
POST     /pipeline/{id}/start              Yes     Start pipeline for job

GET      /settings                         Yes     User preferences
PUT      /settings                         Yes     Update preferences

GET      /audit                            Yes     Audit log entries
GET      /audit/{id}                       Yes     Single audit entry

GET      /errors                           Yes     Error log entries
GET      /errors/{id}                      Yes     Single error entry

POST     /evidence                         Yes*    Upload evidence record
GET      /evidence/{id}                    Yes*    Get evidence record

GET      /user-profiles                    Yes     Get supplemental profile
PUT      /user-profiles                    Yes     Update supplemental profile

GET      /health                           No      Service health check
```

> `Yes*` = JWT required, but Extension uses a dedicated API key (not user JWT) for server-to-server calls.

---

## 7. Auth Endpoints

### POST /api/auth/register

Create a new user account.

**Request:**

```json
{
  "email": "user@example.com",
  "password": "SecureP@ss123",
  "name": "John Doe"
}
```

**Validation:**
- `email`: Valid email format, unique
- `password`: Min 8 chars, uppercase, lowercase, digit, special char
- `name`: 1-100 chars

**Response: 201 Created**

```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "name": "John Doe",
    "created_at": "2026-08-23T12:00:00Z"
  },
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Side effects:**
- Inserts into `users` table
- Creates default `settings` rows (chat_mode: bot, theme: dark)
- Logs `user_registered` to `audit_logs`

---

### POST /api/auth/login

Authenticate and receive JWT pair.

**Request:**

```json
{
  "email": "user@example.com",
  "password": "SecureP@ss123"
}
```

**Response: 200 OK**

```json
{
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "user@example.com",
    "name": "John Doe"
  },
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 900
}
```

**Side effects:**
- Logs `user_logged_in` to `audit_logs`

---

### POST /api/auth/refresh

Exchange a valid refresh token for a new access token.

**Request:**

```json
{
  "refresh_token": "eyJhbGciOiJIUzI1NiIs..."
}
```

**Response: 200 OK**

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer",
  "expires_in": 900
}
```

---

### POST /api/auth/logout

Terminate the current session by revoking the presented refresh token server-side.

**Headers:** `Authorization: Bearer <refresh_token>`

**Response: 200 OK**

```json
{
  "status": "ok"
}
```

**Side effects:**
- Marks the refresh token's `auth_sessions` row (migration 026) as revoked (`revoked_at` set).
- Subsequent refresh with the revoked token fails with `AUTH_TOKEN_INVALID` (401).
- No audit action is emitted — logout is not an audited action in v1 (canonical set closed).

**Errors:**
- `AUTH_TOKEN_INVALID` (401) — malformed, expired, or already-revoked refresh token

---

### GET /api/auth/me

Get the current authenticated user's profile.

**Headers:** `Authorization: Bearer <token>`

**Response: 200 OK**

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "email": "user@example.com",
  "name": "John Doe",
  "created_at": "2026-08-23T12:00:00Z",
  "updated_at": "2026-08-23T12:00:00Z"
}
```

---

## 8. Profile Endpoints

### POST /api/profiles/upload

Upload a resume PDF. The backend parses it into JSONResume format.

**Request:** `multipart/form-data`

| Field    | Type   | Required | Description |
|----------|--------|----------|-------------|
| `file`   | file   | Yes      | Resume PDF (max 10MB) |

**Response: 201 Created**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "original_pdf_url": "/data/profiles/user_id/profile_id/original.pdf",
  "json_resume": {
    "basics": {
      "name": "John Doe",
      "email": "john@example.com",
      "phone": "+1-555-0123",
      "summary": "Senior Backend Engineer with 5+ years..."
    },
    "work": [...],
    "education": [...],
    "skills": [...]
  },
  "created_at": "2026-08-23T12:00:00Z"
}
```

**Side effects:**
- Saves PDF to `/data/profiles/{user_id}/{profile_id}/original.pdf`
- Parses PDF → JSONResume via `hiring-agent-main` (pdf.py, pymupdf_rag.py)
- Inserts into `profiles` table
- Logs `profile_uploaded` to `audit_logs`

---

### GET /api/profiles

List all profiles for the current user.

**Response: 200 OK**

```json
{
  "data": [
    {
      "id": "660e8400-e29b-41d4-a716-446655440001",
      "original_pdf_url": "/data/profiles/user_id/profile_id/original.pdf",
      "last_scored_at": "2026-08-23T12:05:00Z",
      "created_at": "2026-08-23T12:00:00Z"
    }
  ],
  "pagination": {
    "next_cursor": null,
    "has_more": false,
    "total": 1
  }
}
```

---

### GET /api/profiles/current

Get the active profile (most recently uploaded).

**Response: 200 OK**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "original_pdf_url": "/data/profiles/user_id/profile_id/original.pdf",
  "json_resume": {
    "basics": {...},
    "work": [...],
    "education": [...],
    "skills": [...]
  },
  "last_scored_at": "2026-08-23T12:05:00Z",
  "created_at": "2026-08-23T12:00:00Z"
}
```

---

### PUT /api/profiles/{id}

Update a profile's JSONResume data.

**Request:**

```json
{
  "json_resume": {
    "basics": {
      "name": "John Doe",
      "summary": "Updated summary with Kubernetes experience..."
    },
    "work": [...],
    "skills": [...]
  }
}
```

**Response: 200 OK**

```json
{
  "id": "660e8400-e29b-41d4-a716-446655440001",
  "json_resume": {...},
  "updated_at": "2026-08-23T12:10:00Z"
}
```

**Side effects:**
- Logs `profile_uploaded` to `audit_logs`

---

### POST /api/profiles/{id}/analyze

Trigger scoring of the profile against a specific job.

**Request:**

```json
{
  "job_id": "770e8400-e29b-41d4-a716-446655440002"
}
```

**Response: 202 Accepted**

```json
{
  "status": "scoring",
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "profile_id": "660e8400-e29b-41d4-a716-446655440001",
  "message": "Scoring initiated. Check job status for results."
}
```

**Side effects:**
- Calls `hiring-agent-main` evaluator.py + roles.py
- Calls LLM Router for scoring
- Updates `jobs.score` and `jobs.status = scored`
- Logs `profile_scored` + `job_scored` to `audit_logs`
- Inserts into `provider_usage`

---

## 9. Job Endpoints

### GET /api/jobs

List jobs with optional filters.

**Query Parameters:**

| Parameter | Type   | Description |
|-----------|--------|-------------|
| `status`  | string | Filter by status (discovered, scored, approved, applying, applied, rejected, skipped, failed) |
| `platform`| string | Filter by platform (greenhouse, lever, linkedin, indeed, workday, generic) |
| `source`  | string | Filter by source (telegram, discord, manual) |
| `limit`   | int    | Items per page (default 20, max 100) |
| `cursor`  | uuid   | Pagination cursor |

**Response: 200 OK**

```json
{
  "data": [
    {
      "id": "770e8400-e29b-41d4-a716-446655440002",
      "title": "Senior Backend Engineer",
      "company": "Acme Corp",
      "url": "https://boards.greenhouse.io/acme/jobs/12345",
      "platform": "greenhouse",
      "source": "telegram",
      "status": "discovered",
      "score": null,
      "raw_message": "Hiring: Senior Backend Engineer...",
      "created_at": "2026-08-23T12:00:00Z",
      "updated_at": "2026-08-23T12:00:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "770e8400-e29b-41d4-a716-446655440002",
    "has_more": true,
    "total": 47
  }
}
```

---

### GET /api/jobs/{id}

Get a single job with full details.

**Response: 200 OK**

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "title": "Senior Backend Engineer",
  "company": "Acme Corp",
  "url": "https://boards.greenhouse.io/acme/jobs/12345",
  "platform": "greenhouse",
  "source": "telegram",
  "status": "scored",
  "score": 87.5,
  "raw_message": "Hiring: Senior Backend Engineer with 5+ years...",
  "created_at": "2026-08-23T12:00:00Z",
  "updated_at": "2026-08-23T12:05:00Z"
}
```

---

### POST /api/jobs/manual

Add a job URL manually.

**Request:**

```json
{
  "url": "https://boards.greenhouse.io/acme/jobs/12345"
}
```

**Response: 201 Created**

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "title": "Senior Backend Engineer",
  "company": "Acme Corp",
  "url": "https://boards.greenhouse.io/acme/jobs/12345",
  "platform": "greenhouse",
  "source": "manual",
  "status": "discovered",
  "created_at": "2026-08-23T12:00:00Z"
}
```

**Side effects:**
- Fetches URL, extracts job details via JD Extractor
- Inserts into `jobs` table
- Logs `job_discovered` to `audit_logs`

---

### POST /api/jobs/{id}/score

Score a specific job against the current profile.

**Response: 202 Accepted**

```json
{
  "status": "scoring",
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "message": "Scoring initiated"
}
```

**Side effects:**
- Calls scoring engine (hiring-agent-main evaluator.py)
- Updates `jobs.status = scored`, `jobs.score = <calculated>`
- Logs `job_scored` to `audit_logs`

---

### POST /api/jobs/{id}/approve

Approve a job for application.

**Response: 200 OK**

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "approved",
  "updated_at": "2026-08-23T12:10:00Z"
}
```

**Side effects:**
- Updates `jobs.status = approved`
- Logs `job_approved` to `audit_logs`

---

### POST /api/jobs/{id}/reject

Reject a job.

**Request (optional):**

```json
{
  "reason": "Not a good fit for my skills"
}
```

**Response: 200 OK**

```json
{
  "id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "rejected",
  "updated_at": "2026-08-23T12:10:00Z"
}
```

**Side effects:**
- Updates `jobs.status = rejected`
- Logs `job_rejected` to `audit_logs`

---

### DELETE /api/jobs/{id}

Remove a job permanently.

**Response: 204 No Content**

**Side effects:**
- Deletes from `jobs` table (cascades to applications, evidence)
- Logs `job_rejected` to `audit_logs`

---

## 10. Application Endpoints

### GET /api/applications/ready

Get queued application packages ready for the Chrome Extension to fill.

**Used by:** Chrome Extension (polls periodically)

**Response: 200 OK**

```json
{
  "data": [
    {
      "id": "880e8400-e29b-41d4-a716-446655440003",
      "job": {
        "id": "770e8400-e29b-41d4-a716-446655440002",
        "title": "Senior Backend Engineer",
        "company": "Acme Corp",
        "url": "https://boards.greenhouse.io/acme/jobs/12345",
        "platform": "greenhouse"
      },
      "optimized_resume": {
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "summary": "Backend engineer with 5+ years..."
      },
      "cover_letter": "Dear Hiring Manager, I am writing to express...",
      "pdf_url": "/data/evidence/user_id/app_id/application.pdf",
      "field_mappings": {
        "first_name": "John",
        "last_name": "Doe",
        "email": "john@example.com",
        "phone": "+1-555-0123",
        "resume_url": "/data/evidence/user_id/app_id/application.pdf",
        "cover_letter": "Dear Hiring Manager...",
        "linkedin_url": "https://linkedin.com/in/johndoe",
        "github_url": "https://github.com/johndoe",
        "website": "https://johndoe.dev",
        "years_experience": "5",
        "desired_salary": "150000",
        "work_authorization": "US Citizen",
        "skills": "Python, FastAPI, PostgreSQL, Docker",
        "education": "B.S. Computer Science",
        "location": "San Francisco, CA",
        "custom_fields": {}
      },
      "status": "created",
      "created_at": "2026-08-23T12:10:00Z"
    }
  ]
}
```

---

### GET /api/applications/{id}

Get a single application package.

**Response: 200 OK**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "job": {
    "id": "770e8400-e29b-41d4-a716-446655440002",
    "title": "Senior Backend Engineer",
    "company": "Acme Corp",
    "url": "https://boards.greenhouse.io/acme/jobs/12345",
    "platform": "greenhouse"
  },
  "profile": {
    "id": "660e8400-e29b-41d4-a716-446655440001"
  },
  "optimized_resume": {...},
  "cover_letter": "Dear Hiring Manager...",
  "pdf_url": "/data/evidence/user_id/app_id/application.pdf",
  "field_mappings": {...},
  "status": "filled",
  "screenshot_url": "/data/evidence/user_id/app_id/screenshot.png",
  "filled_at": "2026-08-23T12:15:00Z",
  "submitted_at": null,
  "created_at": "2026-08-23T12:10:00Z"
}
```

---

### POST /api/applications/{id}/submit

Mark an application as submitted (called by Extension after user clicks Submit).

**Request:**

```json
{
  "screenshot_url": "/data/evidence/user_id/app_id/confirmation.png"
}
```

**Response: 200 OK**

```json
{
  "id": "880e8400-e29b-41d4-a716-446655440003",
  "status": "submitted",
  "submitted_at": "2026-08-23T12:20:00Z"
}
```

**Side effects:**
- Updates `applications.status = submitted`, `applications.submitted_at`
- Updates `jobs.status = applied`
- Logs `application_submitted` to `audit_logs`
- Updates `pipeline_runs.status = completed`

---

### POST /api/applications/{id}/fill-details

Record the per-field fill audit trail from the extension (Tier 1/2/3 results).

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

**Response: 200 OK**

```json
{
  "status": "recorded",
  "filled_count": 7,
  "unfilled_count": 1
}
```

**Side effects:**
- Updates `applications.fill_details = <provided>`
- If any field has `filled=false` and `error=requires_human`, application stays `filling`
- Logs `application_fill_details` to `audit_logs`

**Errors:**
- `APPLICATION_NOT_FOUND` (404)

---

## 11. Extension Endpoints

> These endpoints are consumed exclusively by the Chrome Extension. They use a dedicated Extension API key (not user JWT) for server-to-server auth.

### POST /api/extensions/{id}/fill

Tell the Extension to start filling a form.

**Request:**

```json
{
  "field_mappings": {
    "first_name": "John",
    "last_name": "Doe",
    "email": "john@example.com",
    "phone": "+1-555-0123",
    "resume_url": "/data/evidence/user_id/app_id/application.pdf",
    "cover_letter": "Dear Hiring Manager...",
    "linkedin_url": "https://linkedin.com/in/johndoe",
    "github_url": "https://github.com/johndoe",
    "website": "https://johndoe.dev",
    "years_experience": "5",
    "desired_salary": "150000",
    "work_authorization": "US Citizen",
    "skills": "Python, FastAPI, PostgreSQL, Docker",
    "education": "B.S. Computer Science",
    "location": "San Francisco, CA",
    "custom_fields": {}
  },
  "application_id": "880e8400-e29b-41d4-a716-446655440003"
}
```

**Response: 200 OK**

```json
{
  "status": "filling",
  "message": "Form filling initiated"
}
```

**Side effects:**
- Updates `applications.status = filling`
- Extension fills fields with human-like pacing (300-800ms per field)
- Extension captures DOM snapshot after filling

---

### POST /api/extensions/{id}/screenshot

Capture a screenshot of the current page state.

**Request:**

```json
{
  "type": "confirmation",
  "metadata": {
    "url": "https://boards.greenhouse.io/acme/jobs/12345/apply",
    "field_count": 8,
    "filled_count": 8
  }
}
```

**Response: 200 OK**

```json
{
  "evidence_id": "990e8400-e29b-41d4-a716-446655440004",
  "file_url": "/data/evidence/user_id/app_id/screenshot.png",
  "type": "screenshot"
}
```

**Side effects:**
- Saves screenshot to `/data/evidence/{user_id}/{app_id}/screenshot.png`
- Inserts into `evidence` table
- Logs `application_filled` to `audit_logs`

---

### POST /api/extensions/{id}/submit

Confirm the application was submitted by the user.

**Request:**

```json
{
  "screenshot_url": "/data/evidence/user_id/app_id/confirmation.png"
}
```

**Response: 200 OK**

```json
{
  "status": "submitted",
  "message": "Application marked as submitted"
}
```

**Side effects:**
- Updates `applications.status = submitted`, `submitted_at`
- Updates `jobs.status = applied`
- Saves confirmation screenshot to evidence
- Logs `application_submitted` to `audit_logs`

---

### POST /api/extensions/{id}/fill-unmapped

Request LLM-generated values for form fields that didn't match `field_mappings` (Tier 2 fill strategy).

**Request:**

```json
{
  "application_id": "880e8400-e29b-41d4-a716-446655440003",
  "fields": [
    "Why do you want to work at Stripe?",
    "Describe your leadership experience"
  ],
  "jd_context": "Senior Backend Engineer at Stripe. Building payment infrastructure..."
}
```

**Response: 200 OK**

```json
{
  "values": {
    "Why do you want to work at Stripe?": "I'm drawn to Stripe's mission to increase GDP of the internet...",
    "Describe your leadership experience": "In my last role I led a team of 5 engineers..."
  }
}
```

**Side effects:**
- Backend calls LLM via provider chain (Gemini → Ollama → Groq → OpenRouter)
- LLM prompt includes: field labels, JD context, user profile summary
- Logs `llm_fill_request` to `audit_logs`
- Token usage tracked in `provider_usage`

**Errors:**
- `APPLICATION_NOT_FOUND` (404)
- `LLM_PROVIDERS_EXHAUSTED` (503) — all free-tier providers failed

---

## 12. LLM Provider Endpoints

### GET /api/llm/providers

List all LLM providers for the current user.

**Response: 200 OK**

```json
{
  "data": [
    {
      "id": "aa0e8400-e29b-41d4-a716-446655440005",
      "name": "Gemini Flash",
      "base_url": "https://generativelanguage.googleapis.com",
      "model": "gemini-2.0-flash",
      "is_active": true,
      "priority": 1,
      "created_at": "2026-08-23T12:00:00Z"
    },
    {
      "id": "bb0e8400-e29b-41d4-a716-446655440006",
      "name": "Groq Llama",
      "base_url": "https://api.groq.com/openai",
      "model": "llama-3.1-70b-versatile",
      "is_active": true,
      "priority": 2,
      "created_at": "2026-08-23T12:00:00Z"
    }
  ]
}
```

**Note:** `api_key` is never returned in list responses.

---

### POST /api/llm/providers

Add a new LLM provider.

**Request:**

```json
{
  "name": "Gemini Flash",
  "base_url": "https://generativelanguage.googleapis.com",
  "api_key": "AIzaSyD...",
  "model": "gemini-2.0-flash",
  "priority": 1
}
```

**Response: 201 Created**

```json
{
  "id": "aa0e8400-e29b-41d4-a716-446655440005",
  "name": "Gemini Flash",
  "base_url": "https://generativelanguage.googleapis.com",
  "model": "gemini-2.0-flash",
  "is_active": true,
  "priority": 1,
  "created_at": "2026-08-23T12:00:00Z"
}
```

**Side effects:**
- Encrypts `api_key` with AES-256 before storing
- Logs `llm_provider_added` to `audit_logs`

---

### DELETE /api/llm/providers/{id}

Remove an LLM provider.

**Response: 204 No Content**

**Side effects:**
- Deletes from `llm_providers` table
- Logs `llm_provider_removed` to `audit_logs`

---

### POST /api/llm/test

Test an LLM provider connection.

**Request:**

```json
{
  "provider_id": "aa0e8400-e29b-41d4-a716-446655440005",
  "prompt": "Say hello in one word."
}
```

**Response: 200 OK**

```json
{
  "success": true,
  "response": "Hello",
  "latency_ms": 342,
  "model": "gemini-2.0-flash"
}
```

**Response: 422 Provider Test Failed**

```json
{
  "error": {
    "code": "PROVIDER_TEST_FAILED",
    "message": "Connection failed: 401 Unauthorized",
    "details": {
      "provider": "Gemini Flash",
      "status_code": 401
    }
  }
}
```

---

## 13. Telegram Endpoints

### POST /api/telegram/connect

Validate a bot token and start listening.

**Request:**

```json
{
  "bot_token": "1234567890:ABCdefGHIjklMNOpqrsTUVwxyz",
  "groups": ["job_alerts", "tech_jobs"]
}
```

**Response: 200 OK**

```json
{
  "status": "connected",
  "bot_username": "my_job_bot",
  "groups": ["job_alerts", "tech_jobs"],
  "message": "Bot connected and listening"
}
```

**Side effects:**
- Validates token via Telegram Bot API `getMe`
- Subscribes to specified groups/channels
- Inserts into `telegram_connections` table
- Logs `telegram_connected` to `audit_logs`

---

### DELETE /api/telegram/disconnect

Stop the Telegram bot.

**Response: 200 OK**

```json
{
  "status": "disconnected",
  "message": "Bot stopped"
}
```

**Side effects:**
- Updates `telegram_connections.status = disconnected`
- Logs `telegram_disconnected` to `audit_logs`

---

### GET /api/telegram/status

Get Telegram bot health status.

**Response: 200 OK**

```json
{
  "status": "connected",
  "bot_username": "my_job_bot",
  "groups": ["job_alerts", "tech_jobs"],
  "messages_processed": 142,
  "last_message_at": "2026-08-23T11:55:00Z",
  "connected_at": "2026-08-23T12:00:00Z"
}
```

---

### GET /api/telegram/groups

List subscribed Telegram groups/channels.

**Response: 200 OK**

```json
{
  "groups": [
    {
      "name": "job_alerts",
      "member_count": 1250,
      "messages_today": 23
    },
    {
      "name": "tech_jobs",
      "member_count": 890,
      "messages_today": 12
    }
  ]
}
```

---

## 14. Discord Endpoints

### POST /api/discord/connect

Validate a Discord bot token and start listening.

**Request:**

```json
{
  "bot_token": "MTIzNDU2Nzg5...",
  "servers": ["job-alerts", "tech-jobs"]
}
```

**Response: 200 OK**

```json
{
  "status": "active",
  "bot_username": "AutoApply Bot",
  "servers": ["job-alerts", "tech-jobs"],
  "message": "Bot connected and listening"
}
```

**Side effects:**
- Validates token via Discord Bot API `@me`
- Invites bot to specified servers
- Inserts into `discord_connections` table
- Logs `discord_connected` to `audit_logs`

---

### DELETE /api/discord/disconnect

Stop the Discord bot.

**Response: 200 OK**

```json
{
  "status": "inactive",
  "message": "Bot stopped"
}
```

**Side effects:**
- Updates `discord_connections.status = inactive`
- Logs `discord_disconnected` to `audit_logs`

---

### GET /api/discord/status

Get Discord bot health status.

**Response: 200 OK**

```json
{
  "status": "active",
  "bot_username": "AutoApply Bot",
  "servers": ["job-alerts", "tech-jobs"],
  "messages_processed": 87,
  "last_message_at": "2026-08-23T11:50:00Z",
  "connected_at": "2026-08-23T12:00:00Z"
}
```

---

### GET /api/discord/servers

List subscribed Discord servers.

**Response: 200 OK**

```json
{
  "servers": [
    {
      "name": "job-alerts",
      "channel_count": 5,
      "messages_today": 18
    },
    {
      "name": "tech-jobs",
      "channel_count": 3,
      "messages_today": 9
    }
  ]
}
```

---

## 15. Checkpoint Endpoints

### GET /api/checkpoints/pending

List paused pipeline jobs that can be resumed.

**Response: 200 OK**

```json
{
  "data": [
    {
      "id": "cc0e8400-e29b-41d4-a716-446655440007",
      "job": {
        "id": "770e8400-e29b-41d4-a716-446655440002",
        "title": "Senior Backend Engineer",
        "company": "Acme Corp"
      },
      "step": "scoring",
      "error_message": "Gemini rate limited (429)",
      "created_at": "2026-08-23T12:05:00Z",
      "updated_at": "2026-08-23T12:05:00Z"
    }
  ]
}
```

---

### POST /api/checkpoints/{id}/resume

Resume a paused pipeline from the checkpoint.

**Response: 200 OK**

```json
{
  "status": "resumed",
  "checkpoint_id": "cc0e8400-e29b-41d4-a716-446655440007",
  "step": "scoring",
  "message": "Pipeline resumed from scoring step"
}
```

**Side effects:**
- Skips completed steps, restarts from saved step
- Updates `pipeline_runs.status = running`
- Logs `pipeline_resumed` to `audit_logs`

---

## 16. Pipeline Endpoints

### GET /api/pipeline/status

Get the current pipeline execution state.

**Response: 200 OK**

```json
{
  "active_runs": 2,
  "paused_runs": 1,
  "recent_completions": [
    {
      "id": "dd0e8400-e29b-41d4-a716-446655440008",
      "job_title": "Frontend Engineer @ TechCo",
      "status": "completed",
      "steps_run": ["jd_extraction", "rubric_generation", "scoring", "optimization", "package_generation"],
      "total_time_ms": 12500,
      "completed_at": "2026-08-23T12:10:00Z"
    }
  ]
}
```

---

### POST /api/pipeline/{id}/start

Start the pipeline for a specific job.

**Request (optional):**

```json
{
  "steps": ["jd_extraction", "rubric_generation", "scoring", "optimization", "package_generation"]
}
```

**Response: 202 Accepted**

```json
{
  "pipeline_run_id": "dd0e8400-e29b-41d4-a716-446655440008",
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "status": "running",
  "steps": ["jd_extraction", "rubric_generation", "scoring", "optimization", "package_generation"],
  "message": "Pipeline started"
}
```

**Side effects:**
- Inserts into `pipeline_runs` with `status = running`
- Executes steps sequentially:
  1. `jd_extraction` — Fetch URL, extract JD via LLM
  2. `rubric_generation` — Generate scoring rubric from JD
  3. `scoring` — Score profile against rubric
  4. `optimization` — Rewrite resume for this specific job
  5. `package_generation` — Generate PDF, build field mappings
- On failure: saves checkpoint, updates `pipeline_runs.status = failed`
- On success: updates `pipeline_runs.status = completed`
- Logs `pipeline_started`, `pipeline_completed` or `pipeline_failed` to `audit_logs`

**Step enum:**

```
jd_extraction → rubric_generation → scoring → optimization → package_generation
```

---

## 17. Settings Endpoints

### GET /api/settings

Get all settings for the current user.

**Response: 200 OK**

```json
{
  "chat_mode": "bot",
  "theme": "dark",
  "auto_approve_threshold": 80,
  "notifications_enabled": true,
  "llm_chain": ["gemini", "ollama", "groq", "openrouter"]
}
```

---

### PUT /api/settings

Update settings (partial update supported).

**Request:**

```json
{
  "chat_mode": "agent",
  "auto_approve_threshold": 85
}
```

**Response: 200 OK**

```json
{
  "chat_mode": "agent",
  "theme": "dark",
  "auto_approve_threshold": 85,
  "notifications_enabled": true,
  "llm_chain": ["gemini", "ollama", "groq", "openrouter"],
  "updated_at": "2026-08-23T12:10:00Z"
}
```

**Side effects:**
- Upserts into `settings` table
- Logs `settings_updated` to `audit_logs`

**Valid settings keys:**

```
KEY                       TYPE      DEFAULT       DESCRIPTION
──────────────────────────────────────────────────────────────
chat_mode                 string    "bot"         "bot" or "agent"
theme                     string    "dark"        "dark" or "light"
auto_approve_threshold    int       80            Score threshold for auto-approve
notifications_enabled     bool      true          Enable desktop notifications
llm_chain                 string[]  [4 providers] Ordered list of LLM providers to try
```

---

## 18. Audit Log Endpoints

### GET /api/audit

List audit log entries for the current user.

**Query Parameters:**

| Parameter    | Type   | Description |
|--------------|--------|-------------|
| `action`     | string | Filter by action (job_discovered, application_submitted, etc.) |
| `resource_type` | string | Filter by resource type (job, application, profile, etc.) |
| `start_date` | string | ISO 8601 date |
| `end_date`   | string | ISO 8601 date |
| `limit`      | int    | Items per page (default 50, max 200) |
| `cursor`     | uuid   | Pagination cursor |

**Response: 200 OK**

```json
{
  "data": [
    {
      "id": "ee0e8400-e29b-41d4-a716-446655440009",
      "action": "application_submitted",
      "resource_type": "application",
      "resource_id": "880e8400-e29b-41d4-a716-446655440003",
      "details": {
        "job_title": "Senior Backend Engineer",
        "company": "Acme Corp"
      },
      "ip_address": "192.168.1.100",
      "created_at": "2026-08-23T12:20:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "ee0e8400-e29b-41d4-a716-446655440009",
    "has_more": true,
    "total": 142
  }
}
```

---

### GET /api/audit/{id}

Get a single audit log entry.

**Response: 200 OK**

```json
{
  "id": "ee0e8400-e29b-41d4-a716-446655440009",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "action": "application_submitted",
  "resource_type": "application",
  "resource_id": "880e8400-e29b-41d4-a716-446655440003",
  "details": {
    "job_title": "Senior Backend Engineer",
    "company": "Acme Corp"
  },
  "ip_address": "192.168.1.100",
  "created_at": "2026-08-23T12:20:00Z"
}
```

---

## 19. Error Log Endpoints

### GET /api/errors

List error log entries for the current user.

**Query Parameters:**

| Parameter    | Type   | Description |
|--------------|--------|-------------|
| `component`  | string | Filter by component (core_engine, llm_router, etc.) |
| `severity`   | string | Filter by severity (LOW, MEDIUM, HIGH, CRITICAL) |
| `start_date` | string | ISO 8601 date |
| `end_date`   | string | ISO 8601 date |
| `limit`      | int    | Items per page (default 50, max 200) |
| `cursor`     | uuid   | Pagination cursor |

**Response: 200 OK**

```json
{
  "data": [
    {
      "id": "ff0e8400-e29b-41d4-a716-446655440010",
      "component": "llm_router",
      "error_type": "rate_limit",
      "severity": "MEDIUM",
      "message": "Gemini rate limited (429)",
      "context": {
        "provider": "Gemini Flash",
        "status_code": 429,
        "retry_after": 30
      },
      "provider": "Gemini Flash",
      "job_id": "770e8400-e29b-41d4-a716-446655440002",
      "retry_count": 1,
      "next_action": "try_next_provider",
      "created_at": "2026-08-23T12:05:00Z"
    }
  ],
  "pagination": {
    "next_cursor": "ff0e8400-e29b-41d4-a716-446655440010",
    "has_more": true,
    "total": 23
  }
}
```

---

### GET /api/errors/{id}

Get a single error log entry.

**Response: 200 OK**

```json
{
  "id": "ff0e8400-e29b-41d4-a716-446655440010",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "component": "llm_router",
  "error_type": "rate_limit",
  "severity": "MEDIUM",
  "message": "Gemini rate limited (429)",
  "context": {...},
  "provider": "Gemini Flash",
  "job_id": "770e8400-e29b-41d4-a716-446655440002",
  "retry_count": 1,
  "next_action": "try_next_provider",
  "stack_trace": null,
  "created_at": "2026-08-23T12:05:00Z"
}
```

---

## 20. Evidence Endpoints

### POST /api/evidence

Upload an evidence record.

**Request:** `multipart/form-data`

| Field           | Type   | Required | Description |
|-----------------|--------|----------|-------------|
| `application_id`| uuid   | Yes      | Link to application |
| `type`          | string | Yes      | screenshot, pdf, dom_snapshot, profile_diff, jd_raw, message_raw |
| `file`          | file   | No*      | Binary file (for screenshot, pdf, dom_snapshot) |
| `metadata`      | string | No       | JSON string of additional metadata |

> *`file` is required for screenshot/pdf/dom_snapshot types. For profile_diff/jd_raw/message_raw, data is stored as JSONB in `metadata`.

**Response: 201 Created**

```json
{
  "id": "a10e8400-e29b-41d4-a716-446655440011",
  "application_id": "880e8400-e29b-41d4-a716-446655440003",
  "type": "screenshot",
  "file_url": "/data/evidence/user_id/app_id/screenshot.png",
  "metadata": {},
  "created_at": "2026-08-23T12:15:00Z"
}
```

**Side effects:**
- Saves file to `/data/evidence/{user_id}/{app_id}/{filename}`
- Inserts into `evidence` table
- Logs evidence capture event to `audit_logs`

---

### GET /api/evidence/{id}

Get a single evidence record.

**Response: 200 OK**

```json
{
  "id": "a10e8400-e29b-41d4-a716-446655440011",
  "application_id": "880e8400-e29b-41d4-a716-446655440003",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "type": "screenshot",
  "file_url": "/data/evidence/user_id/app_id/screenshot.png",
  "metadata": {},
  "created_at": "2026-08-23T12:15:00Z"
}
```

---

## 21. Webhook Endpoints

Internal webhooks for component-to-component communication within the monolith.

### POST /api/webhooks/telegram/message

Called by the Telegram bot service when a new message arrives.

**Request (internal):**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "chat_id": -1001234567890,
  "chat_title": "job_alerts",
  "message_id": 12345,
  "text": "Hiring: Senior Backend Engineer at Acme Corp...",
  "urls_found": ["https://boards.greenhouse.io/acme/jobs/12345"],
  "attachments": []
}
```

**Response: 200 OK**

```json
{
  "status": "processed",
  "jobs_created": 1,
  "job_ids": ["770e8400-e29b-41d4-a716-446655440002"]
}
```

**Side effects:**
- Inserts into `telegram_messages`
- Extracts URLs, creates `jobs` records
- Logs `job_discovered` to `audit_logs`

---

### POST /api/webhooks/discord/message

Called by the Discord bot service when a new message arrives.

**Request (internal):**

```json
{
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "server_id": 1234567890,
  "server_name": "job-alerts",
  "channel_id": 9876543210,
  "channel_name": "general",
  "message_id": 111222333,
  "author_id": 444555666,
  "is_dm": false,
  "direction": "inbound",
  "text": "Hiring: Senior Backend Engineer at Acme Corp...",
  "urls_found": ["https://boards.greenhouse.io/acme/jobs/12345"]
}
```

**Response: 200 OK**

```json
{
  "status": "processed",
  "jobs_created": 1,
  "job_ids": ["770e8400-e29b-41d4-a716-446655440002"]
}
```

**Side effects:**
- Inserts into `discord_messages`
- Extracts URLs, creates `jobs` records
- Logs `job_discovered` to `audit_logs`

---

## 22. Health Check

### GET /api/health

Check service health. No authentication required.

**Response: 200 OK**

```json
{
  "status": "healthy",
  "version": "0.1.0",
  "uptime_seconds": 86400,
  "database": "connected",
  "telegram_bot": "connected",
  "discord_bot": "connected",
  "llm_providers": {
    "gemini": "healthy",
    "ollama": "healthy",
    "groq": "healthy",
    "openrouter": "healthy"
  },
  "timestamp": "2026-08-23T12:00:00Z"
}
```

---

## 23. User Profile Endpoints

Supplemental personal info for fallback field mapping. Created automatically on user registration.

### GET /api/user-profiles

Get current user's supplemental profile.

**Response: 200 OK**

```json
{
  "id": "b20e8400-e29b-41d4-a716-446655440020",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "phone": "+1-555-0123",
  "linkedin_url": "https://linkedin.com/in/johndoe",
  "github_url": "https://github.com/johndoe",
  "website_url": "https://johndoe.dev",
  "address": "123 Main St",
  "city": "San Francisco",
  "state": "CA",
  "country": "USA",
  "postal_code": "94102",
  "date_of_birth": "1995-05-15",
  "gender": null,
  "ethnicity": null,
  "veteran_status": null,
  "disability_status": null,
  "work_authorization": "US Citizen",
  "custom_fields": {},
  "created_at": "2026-08-23T10:00:00Z",
  "updated_at": "2026-08-23T12:00:00Z"
}
```

### PUT /api/user-profiles

Update supplemental profile. Partial updates allowed.

**Request:**

```json
{
  "phone": "+1-555-0456",
  "linkedin_url": "https://linkedin.com/in/johndoe",
  "github_url": "https://github.com/johndoe"
}
```

**Response: 200 OK**

```json
{
  "id": "b20e8400-e29b-41d4-a716-446655440020",
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "phone": "+1-555-0456",
  "linkedin_url": "https://linkedin.com/in/johndoe",
  "github_url": "https://github.com/johndoe",
  "website_url": "https://johndoe.dev",
  "address": "123 Main St",
  "city": "San Francisco",
  "state": "CA",
  "country": "USA",
  "postal_code": "94102",
  "date_of_birth": "1995-05-15",
  "gender": null,
  "ethnicity": null,
  "veteran_status": null,
  "disability_status": null,
  "work_authorization": "US Citizen",
  "custom_fields": {},
  "created_at": "2026-08-23T10:00:00Z",
  "updated_at": "2026-08-23T12:05:00Z"
}
```

**Side effects:**
- Updates `user_profiles` table
- Logs `user_profile_updated` to `audit_logs`

**Fallback behavior:**
When Core Engine builds `field_mappings`, it checks:
1. `optimized_resume` (JSONResume) → primary source
2. `user_profiles` → fallback for missing fields
3. If still null after both → add to `required_fields[]`

---

## Appendix A: Status Enum Reference

> Canonical source: `docs/database/schema.md`

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

## Appendix B: Audit Action Reference

> Canonical source: `docs/components/observability/database/overview.md`

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

## Appendix C: Evidence Type Reference

```
TYPE           CAPTURED BY        WHEN                    STORAGE
──────────────────────────────────────────────────────────────────
screenshot     Extension          After submit            /data/evidence/{user_id}/{app_id}/screenshot.png
pdf            Extension          After submit            /data/evidence/{user_id}/{app_id}/application.pdf
dom_snapshot   Extension          After fill              /data/evidence/{user_id}/{app_id}/dom_snapshot.json
profile_diff   core_engine        After optimization     JSONB in evidence.metadata
jd_raw         core_engine        After extraction       JSONB in evidence.metadata
message_raw    discovery          On ingestion           JSONB in evidence.metadata
```

---

## Appendix D: Component-to-Endpoint Mapping

```
COMPONENT           CONSUMES ENDPOINTS
──────────────────────────────────────────────────────────────
Frontend (Next.js)  All /api/* endpoints (via browser)
Chrome Extension    /api/applications/ready, /api/applications/{id}/fill-details,
                    /api/extensions/*, /api/evidence
MCP Engine          /api/profiles/*, /api/jobs/*, /api/applications/*,
                    /api/llm/*, /api/checkpoints/*
Chat Interface      /api/jobs/*, /api/pipeline/*, /api/settings,
                    /api/telegram/*, /api/discord/*
Discovery           /api/webhooks/telegram/message (internal)
Discord Adapter     /api/webhooks/discord/message (internal)
Core Engine         Internal function calls (not HTTP)
LLM Router          Internal function calls (not HTTP)
Observability       Internal triggers (not HTTP)
Checkpointing       Internal triggers (not HTTP)
```
