# Core Engine — API Contract

> **Owns:** None (no HTTP endpoints — all internal function calls)
> **Consumed by:** Backend API via direct function imports from `hiring-agent-main`
> **Canonical source:** `docs/api_contracts/schema.md` — core engine is called internally, not via HTTP

---

## Internal Functions (Not HTTP)

The Core Engine exposes 6 internal components that are called as Python function imports, not HTTP endpoints. Backend API imports these directly:

| Component | Source | Function Signature |
|-----------|--------|-------------------|
| Extraction Pipeline | `hiring-agent-main` (pdf.py, pymupdf_rag.py) | `extract_profile(pdf_bytes) → JSONResume` |
| Scoring Engine | `hiring-agent-main` (evaluator.py, roles.py) | `score_profile(json_resume, role) → EvaluationResult` |
| JD Extractor | **New** (AutoApply) | `extract_jd(url) → JobDescription` |
| Rubric Generator | **New** (AutoApply) | `generate_rubric(jd) → RoleDefinition` |
| Optimization Engine | **New** (AutoApply) | `optimize_profile(json_resume, feedback, threshold) → OptimizedResume` |
| PDF Generator | **New** (AutoApply) | `generate_pdf(json_resume) → pdf_path` |

---

## Component Interactions

### Extraction Pipeline → Scoring Engine

```
Input:  PDF bytes (from /api/profiles/upload)
Output: JSONResume object
Used by: profiles table (json_resume column)
```

### JD Extractor → Rubric Generator → Scoring Engine

```
Input:  Job URL (from discovery)
Output: Structured JD → Role Definition → Evaluation Result
Used by: jobs table (score, status columns)
```

### Scoring Engine → Optimization Engine

```
Input:  EvaluationResult (score < threshold)
Output: Optimized JSONResume + diff
Used by: applications table (optimized_resume column)
```

### Optimization Engine → PDF Generator

```
Input:  Optimized JSONResume
Output: ATS-friendly PDF at /data/evidence/{user_id}/{app_id}/application.pdf
Used by: applications table (pdf_url column)
```

---

## LLM Calls

All LLM calls go through the LLM Router:

| Component | LLM Call Type | Output |
|-----------|--------------|--------|
| Extraction | Per-section extraction | JSONResume sections |
| Scoring | Evaluation prompt | EvaluationData schema |
| Optimization | Rewrite prompt | Rewritten sections |
| JD Extraction | Parse career page | Structured JD |
| Rubric Generation | Generate scoring criteria | Role definition |

---

## Platform Detection (JD Extractor)

| URL/DOM Pattern | Platform |
|-----------------|----------|
| `greenhouse.io/jobs/*` | greenhouse |
| `lever.co/*` | lever |
| `linkedin.com/jobs/*` | linkedin |
| `indeed.com/viewjob/*` | indeed |
| `workday.com/*` | workday |
| `boards.greenhouse.io/*` | greenhouse |
| `jobs.lever.co/*` | lever |
| (careers page with no pattern) | generic |

---

## Data Flow (Internal)

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
  core_engine → applications (INSERT field_mappings, status=created)

FILL FORM:
  core_engine → applications (UPDATE status=filling → filled)

SUBMIT:
  core_engine → applications (UPDATE status=submitted, submitted_at)

PIPELINE TRACKING:
  core_engine → pipeline_runs (INSERT status=running, started_at)
  core_engine → pipeline_runs (UPDATE steps_run, add step name)
  core_engine → pipeline_runs (UPDATE status=completed/failed)
```

---

## Truthfulness Constraint (Optimization Engine)

```
CAN do:                          CANNOT do:
├── Rephrase bullet points       ├── Add skills not in original
├── Reorder sections             ├── Create fake job experiences
├── Highlight relevant skills    ├── Invent new projects
├── Improve keyword matching     ├── Change dates or companies
├── Better formatting            ├── Add certifications not earned
└── Remove irrelevant info       └── Exaggerate beyond facts
```

---

## Audit Actions

| Internal Event | Audit Action | Resource Type |
|----------------|-------------|---------------|
| Profile extracted | `profile_uploaded` | profile |
| Profile scored | `profile_scored` | profile |
| Job scored | `job_scored` | job |
| Pipeline started | `pipeline_started` | pipeline_run |
| Pipeline completed | `pipeline_completed` | pipeline_run |
| Pipeline failed | `pipeline_failed` | pipeline_run |
| Application created | `application_created` | application |
| Application filled | `application_filled` | application |
| Application submitted | `application_submitted` | application |
| Application failed | `application_failed` | application |
