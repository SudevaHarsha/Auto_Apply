# Core Engine — Database Scope

Owns the job processing pipeline: profile parsing, job storage, application packages, and pipeline execution tracking.

---

## Tables Owned

```
TABLE           PURPOSE                              WRITES
────────────────────────────────────────────────────────────
profiles        Parsed resume (JSONResume format)     CREATE, UPDATE
jobs            Discovered job postings                CREATE, UPDATE
applications    Per-job application package            CREATE, UPDATE
pipeline_runs   Pipeline execution history             CREATE, UPDATE
job_snapshots   Job page snapshot at fetch time        CREATE, UPDATE
```

---

## Tables Read

```
TABLE                READ BY              WHY
─────────────────────────────────────────────────────
llm_providers        core_engine          scoring, optimization, JD extraction
provider_usage       core_engine          logs token usage per LLM call
checkpoints          core_engine          resume failed pipelines
evidence             core_engine          reads evidence for status display
user_profiles        core_engine          fallback for missing resume fields
```

---

## Tables Written (INSERT only, no ownership)

```
TABLE                WRITER               WHY
─────────────────────────────────────────────────────
audit_logs           core_engine          logs job/application events (INSERT)
```

---

## Data Flow

```
UPLOAD RESUME:
  core_engine → profiles (INSERT parsed JSONResume)

DISCOVER JOB:
  core_engine → jobs (INSERT with title, url, platform, status=discovered)

SCORE JOB:
  core_engine → jobs (UPDATE score, status=scored)
  core_engine → provider_usage (INSERT token usage)

OPTIMIZE RESUME:
  core_engine → applications (INSERT optimized_resume, cover_letter, pdf_url)

APPROVE JOB:
  core_engine → jobs (UPDATE status=approved)

CREATE APPLICATION:
  core_engine → applications (INSERT field_mappings, fill_details=[], status=created)

FIELD MAPPING FALLBACK:
  core_engine → profiles (READ json_resume)
  core_engine → user_profiles (READ supplemental info)
  → merge: resume fields + user_profiles fallback
  → if required field still null → add to required_fields[]
  → missing optional fields left for Tier 2 LLM / Tier 3 manual fill

FILL FORM (Tier 1 deterministic match):
  extension → applications (UPDATE status=filling)
  extension → applications (INSERT fill_details per field: tier=deterministic)

FILL FORM (Tier 2 LLM fallback for unmapped fields):
  extension → backend → LLM → extension fills
  extension → applications (INSERT fill_details per field: tier=llm_fallback)

FILL FORM (Tier 3 manual by user):
  user fills remaining fields on the career page
  user_profiles (missing required data surfaced to user)

FILL BLOCKED (SSO wall / CAPTCHA / unsupported platform):
  core_engine → applications (UPDATE status=skipped, skip_reason=<reason>)

SUBMIT:
  core_engine → applications (UPDATE status=submitted, submitted_at)

PIPELINE TRACKING:
  core_engine → pipeline_runs (INSERT status=running, started_at)
  core_engine → pipeline_runs (UPDATE steps_run, add step name)
  core_engine → pipeline_runs (UPDATE status=completed/failed)
```

---

## Relationships

```
users (1) ──────< (N) profiles
users (1) ──────< (N) jobs
users (1) ──────< (N) applications
users (1) ──────< (N) pipeline_runs

profiles (1) ────< (N) applications
jobs (1) ────────< (N) applications
jobs (1) ────────< (N) pipeline_runs

job_snapshots (1) ──< (N) jobs          1 job has 0..1 current_snapshot_id
job_snapshots (1) ──< (N) applications  1 application has 0..1 snapshot_id
```
