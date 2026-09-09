# Glossary

Canonical vocabulary for AutoApply. One term, one meaning.

**IMPORTANT:** Status values are defined ONLY in `docs/database/schema.md`. This glossary reflects them. Do not add status values here that don't exist in schema.md.

---

## Core Entities

| Term | Definition | NOT |
|------|------------|-----|
| **Job** | A discovered job posting from Telegram, Discord, or manual URL. Lives in `jobs` table. | Not an application |
| **Application** | A user-approved job with generated package (PDF, cover letter, field mappings). Lives in `applications` table. | Not a job |
| **Package** | The application package: optimized resume PDF, cover letter, field mappings. A view of an application. | Not a separate entity |
| **Profile** | User's resume data in JSON format. Lives in `profiles` table. | Not an application |
| **User Profile** | Supplemental personal info (phone, social URLs, DOB). Lives in `user_profiles` table. | Not a resume |
| **Run** | A pipeline execution for one job. Lives in `pipeline_runs` table. | Not a checkpoint |
| **Step** | A single unit of work within a pipeline (e.g., jd_extraction, scoring). Checkpointed separately. | Not a stage |
| **Stage** | Deprecated. Use "step". | Don't use this term |
| **Checkpoint** | Saved state of a pipeline step. Allows resume on failure. Lives in `checkpoints` table. | Not a run |

---

## Pipeline Terms

| Term | Definition |
|------|------------|
| **Pipeline** | The full sequence: JD extraction (5-door cascade) → Rubric generation → Scoring → Optimization → Package |
| **Pipeline run** | One execution of the pipeline for one job |
| **Pipeline step** | One stage within the pipeline (5 total) |
| **Checkpoint** | Saved state at a step boundary |
| **Resume** | Continue a pipeline from a checkpoint |
| **Door** | One stage in the 5-door JD extraction cascade (Door 0 = classify, Door 1 = ATS API, Door 2 = JSON-LD, Door 3 = text strip, Door 4 = LLM, Door 5 = gap-fill) |
| **Extraction cascade** | The ordered sequence of doors; each runs only if earlier doors left gaps |
| **Shared extraction cache** | Content-fingerprint cache of JD extraction results, shared across users (public job data, no PII) |
| **Job snapshot** | An immutable extraction result row in `job_snapshots`, keyed by unique `content_hash`. Answers "what exactly did we score against?" Rubrics/packages bind to `snapshot_id` |
| **freshness_state** | Per-job lifecycle state: `fresh \| stale \| expired`, driven by the Freshness FSM (stake-tiered budgets). `expired` blocks fill (`skip_reason='expired'`) |

---

## Source Terms

| Term | Definition |
|------|------------|
| **Discovery** | Finding new jobs from Telegram, Discord, or manual input |
| **Source** | Where a job came from: telegram, discord, manual |
| **Channel** | A Telegram group or Discord server channel being monitored |
| **Group** | Telegram-specific: a group being monitored for job posts |
| **skip_reason** | Lives on `applications`. Records why an application's fill was blocked: SSO wall, CAPTCHA, unsupported platform, or `expired` (JD stale past package-tier budget). Invariant: `applications.status='skipped'` ⇒ `skip_reason IS NOT NULL`. (Jobs have no `skip_reason`; a job not shown to the user is left in `jobs.status`.) |

---

## Application Terms

| Term | Definition |
|------|------------|
| **Approve** | User confirms job should be processed (triggers pipeline) |
| **Reject** | User declines job (removed from queue) |
| **Fill** | Extension fills form fields on job site |
| **Submit** | User manually clicks Submit (extension never auto-submits) |
| **Evidence** | Proof of application: screenshot, PDF, DOM snapshot, profile_diff, jd_raw, message_raw |
| **field_mappings** | Pre-built lookup of all possible answers ({first_name, email, ...}) from resume + user_profiles + JD. Built server-side during package generation |
| **fill_details** | Per-field audit trail of a fill attempt: {label, value, filled, error, required, tier}. Records what was filled, what failed, and why |
| **Fill tier** | How a field is filled: `deterministic` (matched field_mappings at 0 cost) · `llm_fallback` (LLM generated value for unmapped field) · `manual` (user fills by hand) |
| **Deterministic fill (Tier 1)** | Field matches a key in field_mappings → filled instantly, zero LLM cost. (~80% of fields) |
| **LLM fallback (Tier 2)** | Field doesn't match field_mappings → extension sends label + context to backend → LLM generates value. Handles "Why this company?", custom questions (~20% of fields) |
| **Manual fill (Tier 3)** | Field that can't be determined by match or LLM (CAPTCHA, file confirm) → user fills before Submit |
| **Manual package** | Fallback when automation can't fill: PDF + cover letter + answers + step-by-step instructions. Every job yields an actionable application |


---

## LLM Terms

| Term | Definition |
|------|------------|
| **Provider** | An LLM service: Gemini, Ollama, Groq, OpenRouter |
| **Provider chain** | Ordered list of providers with failover |
| **Token** | Unit of text processed by LLM (costs money on paid tiers) |
| **Quota** | Provider's free tier limit (e.g., 1500 req/day for Gemini) |

---

## User Interface Terms

| Term | Definition |
|------|------------|
| **Bot Mode** | Chat interface using regex parsing. Zero token cost. |
| **Agent Mode** | Chat interface using LLM. Flexible, costs tokens. |
| **Dashboard** | Web UI with buttons mapping to REST endpoints |
| **Chat Interface** | Bot Mode + Agent Mode (used by Web UI and Discord) |

---

## Status Values

**Source of truth:** `docs/database/schema.md` (migration definitions)

### jobs.status
```
discovered   → New job found, not yet scored
scored       → Score calculated by LLM
approved     → User approved, pipeline starting
applying     → Extension filling form
applied      → Application submitted
rejected     → User rejected
skipped      → User skipped
failed       → Pipeline or application failed
```

### applications.status
```
created      → Application record created
filling      → Extension filling form
filled       → Form filled, waiting for submit
submitted    → User submitted
skipped      → Fill blocked (SSO wall, CAPTCHA, unsupported platform); skip_reason filled
failed       → Fill or submit failed
```

### pipeline_runs.status
```
running      → Pipeline executing
completed    → Pipeline finished successfully
failed       → Pipeline execution failed
paused       → Pipeline paused at checkpoint
```

### telegram_connections.status
```
connected      → Bot connected and listening
disconnected   → Bot disconnected
error          → Bot connection error
```

### discord_connections.status
```
active         → Bot connected and listening
inactive       → Bot disconnected
error          → Bot connection error
```

### audit_logs.action
```
Canonical list defined in observability/database/overview.md
```

---

## Forbidden Terms

| Term | Use Instead |
|------|-------------|
| stage | step |
| pipeline stage | pipeline step |
| job application | application |
| apply | submit |
| run pipeline | start pipeline |
| pipeline run | run (in prose; table name is `pipeline_runs`) |

---

## Table Ownership

| Table | Owner |
|-------|-------|
| users | auth |
| profiles | core_engine |
| api_keys | auth |
| settings | auth |
| user_profiles | auth |
| jobs | core_engine |
| applications | core_engine |
| job_snapshots | core_engine (shared, RLS-exempt) |
| evidence | chrome_extension |
| pipeline_runs | core_engine |
| checkpoints | checkpointing |
| llm_providers | llm_router |
| provider_usage | llm_router |
| telegram_connections | discovery |
| telegram_messages | discovery |
| discord_connections | discord |
| discord_messages | discord |
| audit_logs | observability |
| error_logs | observability |
| rate_limit_state | llm_router |
