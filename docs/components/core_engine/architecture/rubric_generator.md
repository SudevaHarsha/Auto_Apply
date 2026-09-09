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
│  │  Output: 3 files (in-memory or temp)                   │   │
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
  1. Rubric Generator creates role.json in MEMORY (not disk)
  2. Creates criteria.jinja in MEMORY
  3. Creates system_message.jinja in MEMORY
  4. Passes them directly to ResumeEvaluator

No files written to disk. No role directory needed.
The existing Role dataclass and evaluator work unchanged.
```
