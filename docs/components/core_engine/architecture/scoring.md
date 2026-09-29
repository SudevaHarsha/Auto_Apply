# Core Engine — Scoring Engine

Evaluates a resume against a role's rubric using LLM.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     SCORING ENGINE                            │
│                                                               │
│  INPUTS:                                                      │
│  ┌──────────────────┐   ┌──────────────────┐                  │
│  │  JSONResume      │   │  Role Definition │                  │
│  │  (user profile)  │   │  (rubric)        │                  │
│  └────────┬─────────┘   └────────┬─────────┘                  │
│           │                      │                            │
│           │  ┌───────────────────┘                            │
│           │  │                                                │
│           ▼  ▼                                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │                                                        │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │  1. Convert JSONResume → Text                    │  │   │
│  │  │     (for LLM consumption)                        │  │   │
│  │  └──────────────────────┬───────────────────────────┘  │   │
│  │                         │                              │   │
│  │                         ▼                              │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │  2. Render Evaluation Prompt                     │  │   │
│  │  │                                                  │  │   │
│  │  │  criteria.jinja + system_message.jinja           │  │   │
│  │  │  + resume_text + role categories                 │  │   │
│  │  └──────────────────────┬───────────────────────────┘  │   │
│  │                         │                              │   │
│  │                         ▼                              │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │  3. Call LLM with structured output             │  │   │
│  │  │                                                  │  │   │
│  │  │  Input:  resume_text + scoring criteria          │  │   │
│  │  │  Output: JSON matching EvaluationData schema     │  │   │
│  │  └──────────────────────┬───────────────────────────┘  │   │
│  │                         │                              │   │
│  │                         ▼                              │   │
│  │  ┌──────────────────────────────────────────────────┐  │   │
│  │  │  4. Parse & Validate Response                    │  │   │
│  │  │                                                  │  │   │
│  │  │  EvaluationData:                                 │  │   │
│  │  │  ├── scores: {category: {score, max, evidence}} │  │   │
│  │  │  ├── bonus_points: {total, breakdown}           │  │   │
│  │  │  ├── deductions: {total, reasons}               │  │   │
│  │  │  ├── key_strengths: [str, str, ...]             │  │   │
│  │  │  └── areas_for_improvement: [str, str, ...]     │  │   │
│  │  └──────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  OUTPUT:                                                      │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  EvaluationResult                                      │   │
│  │  ├── total_score: 70 / 90                                │   │
│  │  ├── category_scores:                                  │   │
│  │  │   ├── technical_skills: 18/25                       │   │
│  │  │   ├── experience: 22/30                             │   │
│  │  │   ├── education: 15/20                              │   │
│  │  │   └── projects: 12/15                               │   │
│  │  ├── bonus: +5.0                                       │   │
│  │  ├── deductions: -2.0                                  │   │
│  │  ├── strengths: ["Strong Python skills", ...]          │   │
│  │  └── weaknesses: ["No Kubernetes experience", ...]     │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## Role Definition Structure

Each role defines what categories to score and how much each is worth:

```
Role: "Backend Engineer at Acme"
│
├── role.json
│   ├── categories: [
│   │   { key: "technical_skills", max: 25, label: "Technical Skills" },
│   │   { key: "experience",       max: 30, label: "Experience" },
│   │   { key: "education",        max: 20, label: "Education" },
│   │   { key: "projects",         max: 15, label: "Projects" }
│   │ ]
│   ├── bonus_max: 10
│   └── position_title: "Backend Engineer at Acme"
│
├── criteria.jinja
│   └── "Score the resume for these categories:
│        Technical Skills (0-25): Python, databases, APIs...
│        Experience (0-30): Years, leadership, production..."
│
└── system_message.jinja
    └── "You are an expert technical recruiter...
         Be fair, objective, score only on demonstrated skills..."
```

---

## Rubric Source & Persistence

The `Role Definition` (role.json shape + criteria.jinja + system_message.jinja) is **generated per
JD** by the Rubric Generator (see `rubric_generator.md`) — it is never shipped as role files. For the
current scoring op it is held in memory; the generated rubric is additionally **persisted to the
shared `rubric_cache` table** keyed `(job_id, snapshot_id, schema_version)` (S7 D58), so re-scoring
the same JD snapshot reuses the cached rubric — no second rubric-generation call — across users and
across S8 re-scores. Cache miss ⇒ 1 rubric-generation LLM call + one cache write.

Step 3's LLM call runs through the **LLM Router** (`route_llm_request`, S4) with `json_mode` +
the `EvaluationData` `model_json_schema()` — failover / usage / audit are owned by the router (S7
D48).
