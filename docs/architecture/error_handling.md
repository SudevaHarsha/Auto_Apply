# Error Handling Architecture

Complete error handling strategy for AutoApply's real-time pipeline.

---

## Error Taxonomy

```
SEVERITY    DESCRIPTION                     ACTION
────────────────────────────────────────────────────────────
CRITICAL    System cannot function           Alert user, stop pipeline
HIGH        Feature degraded                Retry, fallback, alert
MEDIUM      Temporary failure               Retry with backoff
LOW         Non-critical miss               Log, continue
INFO        Expected behavior               Log only
```

---

## Error Codes

All API responses use these codes. Consistent across all components.

```
CODE                        HTTP STATUS   SEVERITY   DESCRIPTION
───────────────────────────────────────────────────────────────────
SUCCESS                     200           INFO       Operation succeeded
CREATED                     201           INFO       Resource created
NO_CONTENT                  204           INFO       Operation succeeded, no body

BAD_REQUEST                 400           LOW        Invalid input
INVALID_STATE               400           LOW        Operation not allowed in current state
VALIDATION_ERROR            400           LOW        Request validation failed

UNAUTHORIZED                401           HIGH       Authentication required
INVALID_TOKEN               401           HIGH       Token expired or invalid
FORBIDDEN                   403           HIGH       Insufficient permissions

NOT_FOUND                   404           LOW        Resource not found
DUPLICATE_ENTRY             409           LOW        Resource already exists

RATE_LIMITED                429           MEDIUM     Too many requests
PROVIDER_RATE_LIMITED       429           HIGH       LLM provider rate limited
QUOTA_EXHAUSTED             429           HIGH       Provider quota exceeded

INTERNAL_ERROR              500           CRITICAL   Server error
DATABASE_ERROR              500           CRITICAL   Database connection failed
PROVIDER_UNAVAILABLE        503           HIGH       LLM provider down
PIPELINE_FAILED             500           HIGH       Pipeline execution failed
ALL_PROVIDERS_EXHAUSTED     503           CRITICAL   No LLM providers available

EXTENSION_DISCONNECTED      503           HIGH       Chrome extension offline
ELEMENT_NOT_FOUND           400           LOW        Form element missing
FILL_FAILED                 400           LOW        Form fill error
SUBMIT_FAILED               400           MEDIUM     Form submit error

BOT_DISCONNECTED            503           HIGH       Telegram/Discord bot offline
MESSAGE_PARSE_FAILED        400           LOW        Message format invalid
URL_EXTRACT_FAILED          400           LOW        No URL found in message
```

---

## Error Response Format

```json
{
  "error": {
    "code": "PROVIDER_RATE_LIMITED",
    "message": "Gemini rate limited, trying Ollama",
    "details": {
      "provider": "gemini",
      "retry_after": 60,
      "next_provider": "ollama"
    },
    "job_id": "abc-123",
    "timestamp": "2025-08-20T10:30:00Z"
  }
}
```

---

## Error Categories

```
CATEGORY                  SOURCE                  SEVERITY   RETRY
──────────────────────────────────────────────────────────────────────
LLM Provider
  rate_limit              429 from provider       HIGH       yes (next provider)
  provider_down           500/503 from provider   HIGH       yes (next provider)
  timeout                 no response in 30s      HIGH       yes (next provider)
  invalid_response        malformed JSON          MEDIUM     yes (same provider)
  quota_exhausted         403/quota exceeded      HIGH       yes (next provider)

Pipeline
  step_failure            any step crashes        MEDIUM     yes (checkpoint)
  extraction_failure      PDF→JSON fails          MEDIUM     yes (checkpoint)
  scoring_failure         LLM scoring fails       MEDIUM     yes (checkpoint)
  optimization_failure    LLM rewrite fails       MEDIUM     yes (checkpoint)
  pdf_generation_failure  PDF rendering fails     LOW        yes (same step)

Chrome Extension
  element_not_found       form field missing      LOW        no (manual)
  page_not_loaded         career page down        MEDIUM     yes (retry)
  fill_failed             form filling error      LOW        no (manual)
  screenshot_failed       capture error           LOW        no (log)

Discovery
  bot_disconnected        Telegram bot down       HIGH       yes (reconnect)
  message_parse_failed    malformed message       LOW        no (log)
  url_extract_failed      no URL in message       INFO       no (log)
  rate_limit              Telegram API limit      MEDIUM     yes (backoff)

Database
  connection_lost         DB unreachable          CRITICAL   yes (reconnect)
  deadlock                concurrent writes       MEDIUM     yes (retry)
  constraint_violation    data integrity          HIGH       no (fix data)
  query_timeout           slow query              MEDIUM     yes (retry)

Network
  dns_failure             DNS unreachable         CRITICAL   yes (reconnect)
  connection_timeout      network down            HIGH       yes (reconnect)
  tls_failure             cert error              CRITICAL   no (alert)
```

---

## Per-Component Error Handling

### LLM Router

```
┌─────────────────────────────────────────────────────────────┐
│                    LLM ROUTER ERROR FLOW                      │
│                                                               │
│  Request → Provider A (Gemini)                                │
│     │                                                          │
│     ├── 200 OK → return response, reset circuit               │
│     │                                                          │
│     ├── 429 Rate Limit:                                       │
│     │   ├── Parse Retry-After header                          │
│     │   ├── Open circuit for cooldown                         │
│     │   ├── Log to provider_usage (success=false)             │
│     │   └── Try Provider B (Ollama)                           │
│     │                                                          │
│     ├── 500 Server Error:                                     │
│     │   ├── Open circuit for 60s                              │
│     │   ├── Log to provider_usage                             │
│     │   └── Try Provider B                                    │
│     │                                                          │
│     ├── Timeout (30s):                                        │
│     │   ├── Open circuit for 30s                              │
│     │   ├── Log to provider_usage                             │
│     │   └── Try Provider B                                    │
│     │                                                          │
│     └── All providers failed:                                 │
│         ├── Save checkpoint (pipeline_state, step)            │
│         ├── Log to audit_logs (action: all_providers_exhausted)│
│         ├── Notify user (dashboard alert)                     │
│         └── Return error to caller                            │
└─────────────────────────────────────────────────────────────┘
```

```
Circuit Breaker States:

CLOSED (healthy):
  └── Request goes through
  └── On failure → OPEN

OPEN (failed):
  └── Request skipped immediately
  └── After cooldown → HALF_OPEN

HALF_OPEN (testing):
  └── One request goes through
  └── On success → CLOSED
  └── On failure → OPEN (cooldown doubled)
```

---

### Core Engine Pipeline

```
┌─────────────────────────────────────────────────────────────┐
│                 PIPELINE ERROR FLOW                           │
│                                                               │
│  Step 1: JD Extraction                                        │
│  ├── Fetch page → 404? → mark job failed, skip               │
│  ├── Fetch page → timeout? → retry 2x, then fail             │
│  ├── Parse HTML → empty? → mark job failed                    │
│  └── CHECKPOINT save → proceed to Step 2                     │
│                                                               │
│  Step 2: Rubric Generation                                   │
│  ├── LLM call → fails? → try next provider                   │
│  ├── LLM response → invalid JSON? → retry same provider      │
│  └── CHECKPOINT save → proceed to Step 3                     │
│                                                               │
│  Step 3: Scoring                                             │
│  ├── LLM call → fails? → try next provider                   │
│  ├── LLM response → invalid score? → retry same provider     │
│  └── CHECKPOINT save → proceed to Step 4                     │
│                                                               │
│  Step 4: Optimization                                        │
│  ├── LLM call → fails? → try next provider                   │
│  ├── Rewritten content → dishonest? → reject, use original   │
│  └── CHECKPOINT save → proceed to Step 5                     │
│                                                               │
│  Step 5: Package Generation                                  │
│  ├── PDF generation → fails? → retry same step               │
│  ├── Field mapping → fails? → use generic mapping            │
│  └── CHECKPOINT save → ready for extension                   │
│                                                               │
│  ANY STEP FAILS:                                             │
│  ├── Save checkpoint with error_message                      │
│  ├── Update job status to failed                             │
│  ├── Log to pipeline_runs (status=failed)                    │
│  ├── Log to audit_logs (action: pipeline_failed)             │
│  └── Notify user                                             │
└─────────────────────────────────────────────────────────────┘
```

---

### Chrome Extension

```
┌─────────────────────────────────────────────────────────────┐
│               CHROME EXTENSION ERROR FLOW                    │
│                                                               │
│  Form Filling:                                                │
│  ├── Element not found:                                      │
│  │   ├── Log to evidence (type=dom_snapshot)                 │
│  │   ├── Add to unfilled_fields list                         │
│  │   ├── Continue filling other fields                       │
│  │   └── Report partial fill to backend                      │
│  │                                                          │
│  ├── Page not loaded:                                        │
│  │   ├── Retry page load (3x with 2s delay)                 │
│  │   ├── If still failing → report to backend                │
│  │   └── Backend marks application as failed                 │
│  │                                                          │
│  ├── Fill failed (value rejected):                           │
│  │   ├── Try alternative input method (direct value)         │
│  │   ├── If still failing → skip field                       │
│  │   └── Report to backend with field_name + error           │
│  │                                                          │
│  └── Screenshot failed:                                      │
│      ├── Skip screenshot                                     │
│      ├── Log warning                                         │
│      └── Continue (non-critical)                             │
│                                                               │
│  SUBMIT:                                                      │
│  ├── User clicks submit (extension never auto-submits)       │
│  ├── Wait 5s for confirmation page                           │
│  ├── Capture screenshot                                      │
│  └── Report success/failure to backend                       │
└─────────────────────────────────────────────────────────────┘
```

---

### Discovery (Telegram)

```
┌─────────────────────────────────────────────────────────────┐
│              TELEGRAM ERROR FLOW                              │
│                                                               │
│  Bot Connection:                                              │
│  ├── Disconnected:                                           │
│  │   ├── Auto-reconnect (3x with exponential backoff)        │
│  │   ├── Update telegram_connections (status=error)          │
│  │   └── Notify user                                         │
│  │                                                          │
│  ├── Rate limited (429):                                     │
│  │   ├── Wait Retry-After seconds                            │
│  │   └── Resume listening                                    │
│  │                                                          │
│  └── Invalid token:                                          │
│      ├── Stop bot                                            │
│      ├── Update telegram_connections (status=error)          │
│      └── Notify user to reconfigure                          │
│                                                               │
│  Message Processing:                                          │
│  ├── No URLs found → log, skip                               │
│  ├── URL extraction failed → log, skip                       │
│  ├── Duplicate URL → skip (already in jobs)                  │
│  └── Job creation failed → log, skip                         │
└─────────────────────────────────────────────────────────────┘
```

---

## Error Propagation

```
┌─────────────────────────────────────────────────────────────┐
│              ERROR PROPAGATION RULES                          │
│                                                               │
│  Rule 1: Errors propagate UP, not DOWN                        │
│  ├── Extension failure → backend → frontend alert            │
│  ├── LLM failure → core engine → backend → frontend         │
│  └── DB failure → all components → system alert              │
│                                                               │
│  Rule 2: Each component handles its own retries              │
│  ├── LLM Router retries across providers                     │
│  ├── Core Engine retries across pipeline steps               │
│  ├── Extension retries page loads                            │
│  └── Discovery retries bot connections                       │
│                                                               │
│  Rule 3: Failures are logged at the point of failure         │
│  ├── provider_usage for LLM errors                           │
│  ├── checkpoints for pipeline errors                         │
│  ├── evidence for extension errors                           │
│  ├── telegram_messages for discovery errors                  │
│  └── audit_logs for all errors                               │
│                                                               │
│  Rule 4: User is notified only for actionable errors         │
│  ├── All providers exhausted → "switch keys or wait"         │
│  ├── Pipeline failed → "resume or discard"                   │
│  ├── Bot disconnected → "reconfigure bot"                    │
│  └── Rate limit → silent (auto-fallback)                     │
└─────────────────────────────────────────────────────────────┘
```

---

## Retry Policies

```
ERROR TYPE              MAX RETRIES   BACKOFF              RESET ON
──────────────────────────────────────────────────────────────────────
LLM rate_limit          3             exponential (1,2,4s) next success
LLM provider_down       2             fixed (5s)           next success
LLM timeout             2             fixed (10s)          next success
LLM invalid_response    1             none                 next success
Pipeline step_fail      1             none (checkpoint)    next success
Page load timeout       3             fixed (2s)           next success
Bot disconnected        3             exponential (1,2,4s) next success
DB connection_lost      5             exponential (1,2,4,8,16s) next success
DB deadlock             3             random (0-1s)        next success
Extension element_nf    0             none                 never (manual)
Extension fill_failed   0             none                 never (manual)
```

---

## Failed Jobs Queue

```
Jobs that fail repeatedly stay in "failed" status:

1. Job fails → status = "failed"
2. Failed jobs shown in dashboard under "Failed Jobs"
3. User can:
   ├── Retry manually → status = "discovered" (restart pipeline)
   ├── Discard → status = "skipped"
   └── Edit job details → fix URL/platform, retry

Failed job cleanup:
├── Jobs older than 30 days → auto-archive (soft delete)
└── User can purge manually
```

---

## User Notification Matrix

```
EVENT                         NOTIFICATION              CHANNEL
──────────────────────────────────────────────────────────────────
All providers exhausted       "Switch keys or wait"     Dashboard + Email
Pipeline failed               "Resume or discard"       Dashboard
Bot disconnected              "Reconfigure bot"         Dashboard
Job failed                    "Retry or discard"        Dashboard
Application submitted         "Success!"                Dashboard
Application failed            "Failed - retry?"         Dashboard
Rate limit hit                (silent - auto-fallback)  none
Checkpoint saved              (silent - for resume)     none
```

---

## Error Logging Schema

Every error is logged to the `error_logs` table (INSERT ONLY, immutable):

```sql
INSERT INTO error_logs (user_id, component, error_type, severity, message, context, provider, job_id, retry_count, next_action, stack_trace)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11);
```

Example row:
```json
{
  "id": "uuid",
  "user_id": "uuid",
  "component": "llm_router",
  "error_type": "rate_limit",
  "severity": "HIGH",
  "message": "Gemini rate limited, trying Ollama",
  "context": {"retry_after": 60, "attempt": 1},
  "provider": "gemini",
  "job_id": "uuid",
  "retry_count": 1,
  "next_action": "try_next_provider",
  "stack_trace": null,
  "created_at": "2025-08-20T10:30:00Z"
}
```

Dashboard queries:
```sql
-- All errors for a user
SELECT * FROM error_logs WHERE user_id = $1 ORDER BY created_at DESC;

-- Errors by severity
SELECT * FROM error_logs WHERE user_id = $1 AND severity = 'HIGH';

-- Errors by component
SELECT * FROM error_logs WHERE user_id = $1 AND component = 'llm_router';

-- Errors for a specific job
SELECT * FROM error_logs WHERE user_id = $1 AND job_id = $2;

-- Error count by type (last 24h)
SELECT error_type, COUNT(*) FROM error_logs
WHERE user_id = $1 AND created_at > NOW() - INTERVAL '24 hours'
GROUP BY error_type;
```
