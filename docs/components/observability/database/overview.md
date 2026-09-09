# Observability — Database Scope

Owns audit logging and error logging.

---

## Tables Owned

```
TABLE          PURPOSE                              WRITES
─────────────────────────────────────────────────────────
audit_logs     Immutable action log                  INSERT ONLY
error_logs     Structured error log per component    INSERT ONLY
```

---

## Tables Read

```
TABLE             READ BY              WHY
─────────────────────────────────────────────────────
pipeline_runs     observability        aggregates for dashboard
audit_logs        observability        aggregates for dashboard
error_logs        observability        aggregates for dashboard
```

---

## Data Flow

```
ANY ACTION:
  observability → audit_logs (INSERT action, resource_type, resource_id, details)

ANY ERROR:
  observability → error_logs (INSERT component, error_type, severity, message, context)

DASHBOARD LOAD:
  observability → pipeline_runs (READ for aggregation)
  observability → audit_logs (READ for aggregation)
  observability → error_logs (READ for aggregation)
```

---

## Relationships

```
users (1) ──────< (N) audit_logs
users (1) ──────< (N) error_logs
users (1) ──────< (N) pipeline_runs
jobs (1) ────────< (N) pipeline_runs
```

---

## Immutability Rule

```
audit_logs  — INSERT ONLY, no UPDATE, no DELETE
error_logs  — INSERT ONLY, no UPDATE, no DELETE
  enforced by: application layer + PostgreSQL trigger
```

---

## Canonical Audit Actions

All components must use these actions. No free text.

```
ACTION                          RESOURCE_TYPE     DESCRIPTION
───────────────────────────────────────────────────────────────────
user_created                    user              New user registered (legacy alias)
user_registered                 user              User account created (canonical action)
user_logged_in                  user              User authenticated
user_deleted                    user              User account deleted (anonymized)

profile_uploaded                profile           Resume PDF uploaded
profile_scored                  profile           Resume scored against rubric

job_discovered                  job               New job found (Telegram/Discord/manual)
job_extracted                    job               JD extracted; job_snapshots inserted/hit (content_hash)
job_freshness_changed            job               freshness_state transitioned (fresh→stale→expired)
job_scored                      job               Job scored against profile
job_approved                    job               User approved job
job_rejected                    job               User rejected job

pipeline_started                pipeline_run      Pipeline execution started
pipeline_completed              pipeline_run      Pipeline finished successfully
pipeline_failed                 pipeline_run      Pipeline execution failed
pipeline_paused                 checkpoint        Pipeline paused at checkpoint
pipeline_resumed                checkpoint        Pipeline resumed from checkpoint

application_created             application       Application package generated
application_filled              application       Extension filled form fields
application_fill_details        application       Per-field fill audit trail recorded
application_submitted           application       User submitted application
application_skipped             application       Fill blocked (SSO/CAPTCHA/unsupported); skip_reason set
application_failed              application       Fill or submit failed

llm_provider_added              llm_provider      New provider configured
llm_provider_removed            llm_provider      Provider removed
llm_provider_failed             llm_provider      Provider call failed
llm_fill_request                application       LLM generated values for unmapped form fields (Tier 2)
all_providers_exhausted         system            All providers failed, fallback to Ollama

extension_connected             chrome_extension  Extension connected to backend
extension_disconnected          chrome_extension  Extension disconnected

telegram_connected              telegram          Telegram bot connected
telegram_disconnected           telegram          Telegram bot disconnected

discord_connected               discord           Discord bot connected
discord_disconnected            discord           Discord bot disconnected

user_profile_created            user_profile      Supplemental profile created
user_profile_updated            user_profile      Supplemental profile updated

checkpoint_created              checkpoint        New checkpoint saved
checkpoint_resumed              checkpoint        Checkpoint resumed
settings_updated                settings          User preferences updated

error_logged                    error_logs        Error recorded (links to error_logs.id)
```

---

## Resource Types

```
RESOURCE_TYPE          TABLE                 DESCRIPTION
─────────────────────────────────────────────────────────────
user                   users                 User account
profile                profiles              Resume profile
user_profile           user_profiles         Supplemental personal info
job                    jobs                  Job posting
application            applications          Application package
pipeline_run           pipeline_runs         Pipeline execution
checkpoint             checkpoints           Saved pipeline state
llm_provider           llm_providers         LLM configuration
error_logs             error_logs            Error record (self-reference)
system                 (none)                System-level event
chrome_extension       (none)                Extension event
telegram               telegram_connections  Telegram bot event
discord                discord_connections   Discord bot event
```
