# Observability — API Contract

> **Owns:** None (no HTTP endpoints — database triggers + application layer)
> **Consumed by:** All components via INSERT triggers
> **Canonical source:** `docs/api_contracts/schema.md` §18, §19

---

## Internal Functions (Not HTTP)

Observability is triggered by application-layer INSERT calls from all components. It does not expose HTTP endpoints.

---

## Tables Owned

### audit_logs (INSERT ONLY, no UPDATE, no DELETE)

```sql
CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID,
    details JSONB DEFAULT '{}',
    ip_address INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

### error_logs (INSERT ONLY, no UPDATE, no DELETE)

```sql
CREATE TABLE error_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    component TEXT NOT NULL,
    error_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')),
    message TEXT NOT NULL,
    context JSONB DEFAULT '{}',
    provider TEXT,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    retry_count INTEGER DEFAULT 0,
    next_action TEXT,
    stack_trace TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

---

## Canonical Audit Actions

All components must use these actions. No free text.

| Action | Resource Type | Description |
|--------|--------------|-------------|
| `user_registered` | user | User account created |
| `user_logged_in` | user | User authenticated |
| `user_deleted` | user | User account deleted (anonymized) |
| `profile_uploaded` | profile | Resume PDF uploaded |
| `profile_scored` | profile | Resume scored against rubric |
| `job_discovered` | job | New job found (Telegram/Discord/manual) |
| `job_extracted` | job | JD extracted; job_snapshots inserted/hit (content_hash) |
| `job_freshness_changed` | job | freshness_state transitioned (fresh→stale→expired) |
| `job_scored` | job | Job scored against profile |
| `job_approved` | job | User approved job |
| `job_rejected` | job | User rejected job |
| `pipeline_started` | pipeline_run | Pipeline execution started |
| `pipeline_completed` | pipeline_run | Pipeline finished successfully |
| `pipeline_failed` | pipeline_run | Pipeline execution failed |
| `pipeline_paused` | checkpoint | Pipeline paused at checkpoint |
| `pipeline_resumed` | checkpoint | Pipeline resumed from checkpoint |
| `application_created` | application | Application package generated |
| `application_filled` | application | Extension filled form fields |
| `application_fill_details` | application | Per-field fill audit trail recorded |
| `application_submitted` | application | User submitted application |
| `application_skipped` | application | Fill blocked (SSO/CAPTCHA/unsupported); skip_reason set |
| `application_failed` | application | Fill or submit failed |
| `llm_provider_added` | llm_provider | New provider configured |
| `llm_provider_removed` | llm_provider | Provider removed |
| `llm_provider_failed` | llm_provider | Provider call failed |
| `llm_fill_request` | application | LLM generated values for unmapped form fields (Tier 2) |
| `all_providers_exhausted` | system | All providers failed, fallback to Ollama |
| `extension_connected` | chrome_extension | Extension connected to backend |
| `extension_disconnected` | chrome_extension | Extension disconnected |
| `telegram_connected` | telegram | Telegram bot connected |
| `telegram_disconnected` | telegram | Telegram bot disconnected |
| `discord_connected` | discord | Discord bot connected |
| `discord_disconnected` | discord | Discord bot disconnected |
| `user_profile_created` | user_profile | Supplemental profile created |
| `user_profile_updated` | user_profile | Supplemental profile updated |
| `checkpoint_created` | checkpoint | New checkpoint saved |
| `checkpoint_resumed` | checkpoint | Checkpoint resumed |
| `error_logged` | error_logs | Error recorded (links to error_logs.id) |

---

## Resource Types

| Resource Type | Table | Description |
|---------------|-------|-------------|
| user | users | User account |
| profile | profiles | Resume profile |
| user_profile | user_profiles | Supplemental personal info |
| job | jobs | Job posting |
| application | applications | Application package |
| pipeline_run | pipeline_runs | Pipeline execution |
| checkpoint | checkpoints | Saved pipeline state |
| llm_provider | llm_providers | LLM configuration |
| error_logs | error_logs | Error record (self-reference) |
| system | (none) | System-level event |
| chrome_extension | (none) | Extension event |
| telegram | telegram_connections | Telegram bot event |
| discord | discord_connections | Discord bot event |

---

## GDPR Compliance

### Anonymization (Don't Delete)

For audit_logs and error_logs, GDPR requests are handled via anonymization, not deletion:

```sql
-- Anonymize user data (keep audit trail)
UPDATE audit_logs
SET user_id = '00000000-0000-0000-0000-000000000000',
    ip_address = NULL,
    details = details - 'email' - 'name'
WHERE user_id = '<target_user_id>';

UPDATE error_logs
SET user_id = '00000000-0000-0000-0000-000000000000'
WHERE user_id = '<target_user_id>';
```

### Immunity Triggers

These audit actions are exempt from anonymization (system integrity):

- `user_deleted` — must preserve deletion record
- `error_logged` — must preserve error context
- `all_providers_exhausted` — system-level, no user PII

---

## Immutability Rule

```
audit_logs  — INSERT ONLY, no UPDATE, no DELETE
error_logs  — INSERT ONLY, no UPDATE, no DELETE
  enforced by: application layer + PostgreSQL trigger
```

---

## Dashboard Aggregation

The observability component reads from these tables for dashboard display:

```sql
-- Pipeline success rate
SELECT status, COUNT(*)
FROM pipeline_runs
WHERE user_id = $1
GROUP BY status;

-- Error frequency by component
SELECT component, error_type, COUNT(*)
FROM error_logs
WHERE user_id = $1
  AND created_at > NOW() - INTERVAL '7 days'
GROUP BY component, error_type;

-- Audit trail for a specific job
SELECT action, details, created_at
FROM audit_logs
WHERE user_id = $1
  AND resource_id = $2
ORDER BY created_at;
```

---

## Audit Actions

| Internal Event | Audit Action | Resource Type |
|----------------|-------------|---------------|
| Any action logged | (the action itself) | (the resource) |
| Error recorded | `error_logged` | error_logs |
