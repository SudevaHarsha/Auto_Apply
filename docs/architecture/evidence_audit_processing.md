# Evidence & Audit Processing

How evidence is captured/stored and audit logs are written/queried.

---

## Evidence Processing

### What is Evidence?

Proof that an application was submitted. Six types:

```
TYPE           WHAT                    CAPTURED BY        WHEN
──────────────────────────────────────────────────────────────
screenshot     PNG of confirmation     Extension          After submit
pdf            Filled application PDF  Extension          After submit
dom_snapshot   Raw form field values   Extension          After fill
profile_diff   Resume changes before/after  core_engine   After optimization
jd_raw         Raw job description JSON    core_engine    After extraction
message_raw    Raw source message      discovery          On ingestion
```

### Capture Flow

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Extension   │      │  Backend API │      │  Filesystem  │
│  (Chrome)    │      │  (FastAPI)   │      │ /data/evidence│
└──────┬───────┘      └──────┬───────┘      └──────┬───────┘
       │                     │                     │
       │  1. User clicks     │                     │
       │     Submit          │                     │
       │                     │                     │
       │  2. Page redirects  │                     │
       │     to confirmation │                     │
       │                     │                     │
       │  3. Wait 5s for     │                     │
       │     confirmation    │                     │
       │                     │                     │
       │  4. Capture         │                     │
       │     screenshot      │                     │
       │     (canvas)        │                     │
       │                     │                     │
       │  5. POST            │                     │
       │  /api/evidence      │                     │
       │  {                  │                     │
       │    application_id,  │                     │
       │    type: screenshot,│                     │
       │    file: base64     │                     │
       │  }                  │                     │
       │────────────────────>│                     │
       │                     │  6. Write file to   │
       │                     │     /data/evidence/ │
       │                     │     {user_id}/      │
       │                     │     {app_id}/       │
       │                     │     screenshot.png  │
       │                     │────────────────────>│
       │                     │                     │
       │                     │  7. INSERT into     │
       │                     │     evidence table  │
       │                     │     {               │
       │                     │       application_id│
       │                     │       user_id       │
       │                     │       type          │
       │                     │       file_url      │
       │                     │       metadata      │
       │                     │     }               │
       │                     │                     │
       │  8. Return 201      │                     │
       │<────────────────────│                     │
       │                     │                     │
       │  9. Repeat for      │                     │
       │     PDF + DOM       │                     │
```

### Storage Structure

```
/data/evidence/
├── {user_id}/
│   ├── {application_id}/
│   │   ├── screenshot.png
│   │   ├── application.pdf
│   │   └── dom_snapshot.json
│   ├── {application_id}/
│   │   └── screenshot.png
│   └── ...
```

### Evidence Metadata (stored in DB)

```json
{
  "id": "uuid",
  "application_id": "uuid",
  "user_id": "uuid",
  "type": "screenshot",
  "file_url": "/data/evidence/{user_id}/{app_id}/screenshot.png",
  "metadata": {
    "platform": "greenhouse",
    "page_title": "Application Submitted - Acme Corp",
    "viewport": "1920x1080",
    "captured_at": "2026-08-20T14:32:01Z"
  },
  "created_at": "2026-08-20T14:32:01Z"
}
```

### Evidence Retrieval

```
GET /api/evidence/{id}

Returns:
{
  "id": "uuid",
  "application_id": "uuid",
  "type": "screenshot",
  "file_url": "https://...",
  "metadata": {...},
  "created_at": "..."
}
```

Evidence for a given application is listed via the application view (GET /api/applications/{id}) which references its evidence records.

### Error Handling

```
SCREENSHOT FAILED:
  ├── Skip screenshot (non-critical)
  ├── Log warning to error_logs
  └── Continue with other evidence types

PDF CAPTURE FAILED:
  ├── Retry once
  ├── If still failing → skip
  └── Log to error_logs

DOM SNAPSHOT FAILED:
  ├── Skip (least critical)
  └── Log to error_logs

FILE WRITE FAILED:
  ├── Retry 3x with exponential backoff
  ├── If still failing → save base64 to metadata (fallback)
  └── Log to error_logs
```

---

## Audit Log Processing

### What are Audit Logs?

Immutable record of every action in the system. Write-once, never modify.

### Write Flow

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Any         │      │  Audit       │      │  PostgreSQL  │
│  Component   │      │  Service     │      │  audit_logs  │
└──────┬───────┘      └──────┬───────┘      └──────┬───────┘
       │                     │                     │
       │  1. Action occurs   │                     │
       │     (job discovered,│                     │
       │      scored, etc.)  │                     │
       │                     │                     │
       │  2. Call audit_     │                     │
       │     service.log()   │                     │
       │                     │                     │
       │  3. {               │                     │
       │     user_id,        │                     │
       │     action,         │                     │
       │     resource_type,  │                     │
       │     resource_id,    │                     │
       │     details,        │                     │
       │     ip_address      │                     │
       │     }               │                     │
       │────────────────────>│                     │
       │                     │  4. INSERT INTO     │
       │                     │     audit_logs      │
       │                     │     (immutable)     │
       │                     │────────────────────>│
       │                     │                     │
       │  5. Return          │                     │
       │<────────────────────│                     │
```

### Audit Log Schema

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "action": "job_scored",
  "resource_type": "job",
  "resource_id": "uuid",
  "details": {
    "score": 87,
    "provider": "gemini",
    "latency_ms": 3200
  },
  "ip_address": "192.168.1.1",
  "created_at": "2026-08-20T14:32:01Z"
}
```

### Actions Tracked

Canonical list — see observability/database/overview.md for full definitions.

```
ACTION                    RESOURCE_TYPE    WHEN
──────────────────────────────────────────────────────
user_registered           user             account creation
user_logged_in            user             login
user_deleted              user             account deleted (anonymized)

profile_uploaded          profile          resume upload
profile_scored            profile          resume scored
user_profile_created      user_profiles    supplemental profile row created
user_profile_updated      user_profiles    supplemental profile row updated

job_discovered            job              new job found
job_extracted             job              JD extracted and stored
job_scored                job              scoring complete
job_freshness_changed     job              freshness state changed
job_approved              job              user approved
job_rejected              job              user rejected

application_created       application      package built
application_fill_details  application      fill detail recorded (per field)
application_filled        application      extension filled
application_skipped       application      fill blocked; skip_reason set
application_submitted     application      user submitted
application_failed        application      submission failed

pipeline_started          pipeline_run     pipeline start
pipeline_completed        pipeline_run     pipeline end
pipeline_failed           pipeline_run     pipeline error
pipeline_paused           checkpoint       pipeline paused
pipeline_resumed          checkpoint       checkpoint resume

llm_provider_added        llm_provider     provider configured
llm_provider_removed      llm_provider     provider removed
llm_provider_failed       llm_provider     LLM error
llm_fill_request          llm_provider     Tier 2 fill fallback LLM call
all_providers_exhausted   system           all providers down

settings_updated           settings         user preferences updated

extension_connected       chrome_extension extension connected
extension_disconnected    chrome_extension extension disconnected

telegram_connected        telegram         bot connected
telegram_disconnected     telegram         bot disconnected

discord_connected         discord          bot connected
discord_disconnected      discord          bot disconnected

checkpoint_created        checkpoint       checkpoint saved
checkpoint_resumed        checkpoint       checkpoint resumed

error_logged              error_logs       error recorded
```
### Audit Log Queries

```sql
-- All actions for a user (most recent first)
SELECT * FROM audit_logs
WHERE user_id = $1
ORDER BY created_at DESC
LIMIT 100;

-- All job discoveries
SELECT * FROM audit_logs
WHERE user_id = $1 AND action = 'job_discovered'
ORDER BY created_at DESC;

-- Actions for a specific job
SELECT * FROM audit_logs
WHERE user_id = $1 AND resource_id = $2
ORDER BY created_at;

-- Actions in last 24 hours
SELECT * FROM audit_logs
WHERE user_id = $1 AND created_at > NOW() - INTERVAL '24 hours'
ORDER BY created_at DESC;

-- Action count by type
SELECT action, COUNT(*) as count
FROM audit_logs
WHERE user_id = $1
GROUP BY action
ORDER BY count DESC;
```

### Immutability

```
audit_logs are INSERT ONLY:
  ├── No UPDATE allowed
  ├── No DELETE allowed
  ├── Enforced by PostgreSQL trigger
  └── Violation raises exception

Trigger:
  BEFORE UPDATE OR DELETE ON audit_logs
  FOR EACH ROW
  EXECUTE FUNCTION prevent_audit_log_modification()
```

---

## Error Log Processing

### What are Error Logs?

Structured error records with severity, component, and context.

### Write Flow

```
┌──────────────┐      ┌──────────────┐      ┌──────────────┐
│  Any         │      │  Error       │      │  PostgreSQL  │
│  Component   │      │  Service     │      │  error_logs  │
└──────┬───────┘      └──────┬───────┘      └──────┬───────┘
       │                     │                     │
       │  1. Error occurs    │                     │
       │     (LLM fails,     │                     │
       │      pipeline       │                     │
       │      crashes, etc.) │                     │
       │                     │                     │
       │  2. Call error_     │                     │
       │     service.log()   │                     │
       │                     │                     │
       │  3. {               │                     │
       │     user_id,        │                     │
       │     component,      │                     │
       │     error_type,     │                     │
       │     severity,       │                     │
       │     message,        │                     │
       │     context,        │                     │
       │     provider,       │                     │
       │     job_id,         │                     │
       │     retry_count,    │                     │
       │     next_action,    │                     │
       │     stack_trace     │                     │
       │     }               │                     │
       │────────────────────>│                     │
       │                     │  4. INSERT INTO     │
       │                     │     error_logs      │
       │                     │     (immutable)     │
       │                     │────────────────────>│
```

### Error Log Queries

```sql
-- All errors for a user
SELECT * FROM error_logs
WHERE user_id = $1
ORDER BY created_at DESC;

-- Errors by severity
SELECT * FROM error_logs
WHERE user_id = $1 AND severity = 'HIGH'
ORDER BY created_at DESC;

-- Errors by component
SELECT * FROM error_logs
WHERE user_id = $1 AND component = 'llm_router'
ORDER BY created_at DESC;

-- Errors for a specific job
SELECT * FROM error_logs
WHERE user_id = $1 AND job_id = $2
ORDER BY created_at DESC;

-- Error count by type (last 24h)
SELECT error_type, COUNT(*) as count
FROM error_logs
WHERE user_id = $1 AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY error_type
ORDER BY count DESC;

-- Errors requiring attention (HIGH + CRITICAL)
SELECT * FROM error_logs
WHERE user_id = $1 AND severity IN ('HIGH', 'CRITICAL')
AND created_at > NOW() - INTERVAL '7 days'
ORDER BY created_at DESC;
```

---

## Dashboard Display

### Evidence Gallery

```
┌─────────────────────────────────────────────────────────┐
│  Application: Sr Backend Engineer @ Acme Corp            │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  ┌──────────────────┐  ┌──────────────────┐             │
│  │ Screenshot       │  │ Filled PDF       │             │
│  │ (confirmation)   │  │                  │             │
│  │                  │  │                  │             │
│  │ [View Full Size] │  │ [Download]       │             │
│  └──────────────────┘  └──────────────────┘             │
│                                                          │
│  DOM Snapshot:                                           │
│  {                                                       │
│    "name": "John Doe",                                   │
│    "email": "john@example.com",                          │
│    "phone": "+1-555-0123",                               │
│    "resume": "uploaded"                                  │
│  }                                                       │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Audit Log Timeline

```
┌─────────────────────────────────────────────────────────┐
│  Audit Log — Last 24 Hours                               │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  14:32  application_submitted  Sr Backend @ Acme  ✓     │
│  14:30  application_filled     Sr Backend @ Acme  ✓     │
│  14:28  application_created    Sr Backend @ Acme  ✓     │
│  14:25  job_approved           Sr Backend @ Acme  ✓     │
│  14:22  job_scored             Sr Backend @ Acme  87/100 │
│  14:20  job_discovered         Sr Backend @ Acme  URL   │
│  14:15  profile_uploaded       profile v3         PDF   │
│  14:10  user_logged_in         session started          │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Error Dashboard

```
┌─────────────────────────────────────────────────────────┐
│  Errors — Last 7 Days                                    │
├─────────────────────────────────────────────────────────┤
│                                                          │
│  SEVERITY   COMPONENT      TYPE           COUNT         │
│  ──────────────────────────────────────────────────     │
│  HIGH       llm_router     rate_limit     12            │
│  MEDIUM     core_engine    scoring        3             │
│  LOW        chrome_ext     element_nf     7             │
│                                                          │
│  Recent Errors:                                          │
│  14:32  HIGH   llm_router   Gemini rate limited         │
│         → tried Ollama, succeeded                       │
│  14:15  MEDIUM core_engine  Scoring failed               │
│         → checkpoint saved, resumed                     │
│                                                          │
└─────────────────────────────────────────────────────────┘
```
