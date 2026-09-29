# Core Engine — Rubric Generator

Converts a job description into a scoring rubric (dynamic Role definition).

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     RUBRIC GENERATOR                          │
│                                                               │
│  INPUT: Structured JD from JD Extractor                      │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │                                                        │   │
│  │  ┌──────────────────┐     ┌────────────────────────┐   │   │
│  │  │  Job Description │────▶│  LLM via Router        │   │   │
│  │  │                  │     │                        │   │   │
│  │  │  title           │     │  "Generate a scoring   │   │   │
│  │  │  required_skills │     │   rubric for this role"│   │   │
│  │  │  requirements    │     │                        │   │   │
│  │  │  responsibilities│     └────────────┬───────────┘   │   │
│  │  └──────────────────┘                  │               │   │
│  │                                        ▼               │   │
│  │                         ┌──────────────────────────┐   │   │
│  │                         │  Generated Rubric        │   │   │
│  │                         └──────────────────────────┘   │   │
│  └────────────────────────────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Output: 3 files (in-memory, cached)                   │   │
│  │                                                        │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │  role.json                                       │  │   │
│  │  │  {                                               │  │   │
│  │  │    "position_title": "Senior Backend Eng @ Acme",│  │   │
│  │  │    "categories": [                               │  │   │
│  │  │      {"key": "technical_skills", "max": 30},    │  │   │
│  │  │      {"key": "experience", "max": 35},          │  │   │
│  │  │      {"key": "education", "max": 15},           │  │   │
│  │  │      {"key": "cultural_fit", "max": 20}         │  │   │
│  │  │    ],                                            │  │   │
│  │  │    "bonus_max": 10                               │  │   │
│  │  │  }                                               │  │   │
│  │  └──────────────────────────────────────────────────┘  │   │
│  │                                                        │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │  criteria.jinja                                  │  │   │
│  │  │                                                  │  │   │
│  │  │  "Score this resume for Senior Backend Eng:      │  │   │
│  │  │   Technical Skills (0-30):                       │  │   │
│  │  │   - Python proficiency (0-10)                    │  │   │
│  │  │   - Database design (0-10)                       │  │   │
│  │  │   - API architecture (0-10)                      │  │   │
│  │  │   Experience (0-35):                             │  │   │
│  │  │   - Years of relevant experience (0-15)          │  │   │
│  │  │   - Leadership and mentoring (0-10)              │  │   │
│  │  │   - Production systems (0-10)                    │  │   │
│  │  │   ..."                                           │  │   │
│  │  └──────────────────────────────────────────────────┘  │   │
│  │                                                        │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │  system_message.jinja                            │  │   │
│  │  │                                                  │  │   │
│  │  │  "You are an expert technical recruiter at Acme  │  │   │
│  │  │   evaluating candidates for Senior Backend Eng.  │  │   │
│  │  │   Be fair, objective. Score only on demonstrated │  │   │
│  │  │   skills relevant to this role. No bias based on │  │   │
│  │  │   name, gender, institution, or location."       │  │   │
│  │  └──────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  These 3 files are fed into the Scoring Engine.               │
└──────────────────────────────────────────────────────────────┘
```

---

## How It Uses hiring-agent-main's Role System

```
hiring-agent-main has:
  roles.py → load_role("software_engineering_intern")
           → reads roles/software_engineering_intern/role.json
           → returns Role object

AutoApply does:
  1. Rubric Generator creates role.json in MEMORY (not disk, no role directory)
  2. Creates criteria.jinja + system_message.jinja in MEMORY
  3. Builds the Role and passes it directly to ResumeEvaluator
  4. Persists the generated rubric (role.json shape + rendered templates + rubric_sha256) to the
     shared, RLS-exempt `rubric_cache` table — keyed `(job_id, snapshot_id, schema_version)` — so any
     later score of the same JD snapshot (any user, or an S8 re-score) reuses it without a second
     rubric-generation LLM call.

No files are ever written to disk. No role directory is needed. "In memory" means the Rubric
Generator performs no filesystem I/O for the role; the durable copy of a generated rubric lives in
`rubric_cache` (DB), not in role files. The existing Role dataclass and evaluator work unchanged.

---

## Rubric Persistence (S7)

The generated rubric is saved to the shared `rubric_cache` table (migration 031) so it survives
process restarts and is re-used across users and re-scores:

```
rubric_cache(
  job_id          UUID    → REFERENCES jobs(id) ON DELETE CASCADE
  snapshot_id     UUID    → the exact JD snapshot the rubric was built against
  schema_version  INT     → CURRENT_SCHEMA_VERSION at generation (bump = deliberate re-generation)
  rubric_sha256   TEXT    → content guard, recomputed on read
  rubric          JSONB   → role.json shape + rendered criteria/system + labels/weights
  UNIQUE(job_id, snapshot_id, schema_version)
)
```

Cache hit ⇒ 0 rubric-generation calls (evaluation only); miss ⇒ 1 rubric call, then exactly one
`rubric_cache` row.
```
