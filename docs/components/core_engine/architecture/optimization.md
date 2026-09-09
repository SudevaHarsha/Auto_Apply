# Core Engine — Optimization Engine

Rewrites profile sections to improve ATS score. Constraint: never fabricate experiences.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     OPTIMIZATION ENGINE                           │
│                                                                   │
│  INPUTS:                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐            │
│  │  Current     │  │  Scoring     │  │  Target      │            │
│  │  Profile     │  │  Feedback    │  │  Threshold   │            │
│  │  (JSONResume)│  │  (evidence + │  │  (e.g. 85)   │            │
│  │              │  │  weaknesses) │  │              │            │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘            │
│         │                 │                  │                    │
│         └─────────────────┼──────────────────┘                    │
│                           │                                       │
│                           ▼                                       │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  1. Identify Weak Sections                           │  │   │
│  │  │                                                      │  │   │
│  │  │  Compare category scores → find lowest scoring areas │  │   │
│  │  │  e.g., "projects: 12/15" → focus on projects section │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  2. Generate Rewrite Prompt                          │  │   │
│  │  │                                                      │  │   │
│  │  │  "Rewrite the projects section to better highlight:  │  │   │
│  │  │   - Python backend experience                        │  │   │
│  │  │   - API design skills                                │  │   │
│  │  │   - Database optimization                            │  │   │
│  │  │   DO NOT fabricate any new experiences."              │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  3. LLM Rewrites Section                             │  │   │
│  │  │                                                      │  │   │
│  │  │  Input:  current section + feedback + constraints    │  │   │
│  │  │  Output: rewritten section (same facts, better words)│  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  4. Validate Rewrite                                 │  │   │
│  │  │                                                      │  │   │
│  │  │  ├── Check: no new skills added that weren't in orig │  │   │
│  │  │  ├── Check: no new jobs/companies fabricated         │  │   │
│  │  │  ├── Check: dates still match                        │  │   │
│  │  │  └── Check: word count within ATS limits             │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  5. Build Diff                                       │  │   │
│  │  │                                                      │  │   │
│  │  │  Save before/after diff for evidence viewer:         │  │   │
│  │  │  - What changed                                      │  │   │
│  │  │  - Why it changed                                    │  │   │
│  │  │  - Expected score improvement                        │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  LOOP CONTROL:                                                    │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                                                            │   │
│  │  Score < threshold? ──YES──▶ Optimize ──▶ Re-score ──┐    │   │
│  │       ▲                                              │    │   │
│  │       │          iterations < max? ◀─────────────────┘    │   │
│  │       │               │                                   │   │
│  │       │          YES  │  NO                               │   │
│  │       ◀───────────────┘  │                                │   │
│  │                          ▼                                │   │
│  │                    STOP. Return best profile.             │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  OUTPUT: Optimized JSONResume + diff + final score                │
└──────────────────────────────────────────────────────────────────┘
```

---

## Truthfulness Constraint

```
CAN do:                          CANNOT do:
├── Rephrase bullet points       ├── Add skills not in original
├── Reorder sections             ├── Create fake job experiences
├── Highlight relevant skills    ├── Invent new projects
├── Improve keyword matching     ├── Change dates or companies
├── Better formatting            ├── Add certifications not earned
└── Remove irrelevant info       └── Exaggerate beyond facts

Example:
  BEFORE: "Built REST APIs using Python and Flask"
  AFTER:  "Designed and implemented RESTful APIs using Python/Flask
           for backend services"
  
  Same facts. Better words. No fabrication.
```

---

## Field Mapping Fallback Chain

After optimization, build `field_mappings` by merging resume data with `user_profiles`. This is the **deterministic (Tier 1)** source of answers the extension matches against at fill time. Fields it can't cover fall to the LLM (Tier 2) at fill time — see the **Application Engine** (`application_engine.md`).

```
STEP 1: Extract from optimized_resume (JSONResume)
  name      → optimized_resume.basics.name
  email     → optimized_resume.basics.email
  phone     → optimized_resume.basics.phone
  linkedin  → optimized_resume.basics.profiles[platform=linkedin].url
  github    → optimized_resume.basics.profiles[platform=github].url
  website   → optimized_resume.basics.url

STEP 2: Fallback to user_profiles (if null after Step 1)
  phone     → user_profiles.phone
  linkedin  → user_profiles.linkedin_url
  github    → user_profiles.github_url
  website   → user_profiles.website_url
  address   → user_profiles.address
  city      → user_profiles.city
  state     → user_profiles.state
  country   → user_profiles.country
  postal    → user_profiles.postal_code
  dob       → user_profiles.date_of_birth

STEP 3: Check required fields per platform
  greenhouse: name, email (required), resume (required)
  lever:      name, email (required), resume (required)
  linkedin:   name, email (required), resume (required)
  indeed:     name, email (required), resume (required)
  generic:    name, email (required), resume (required)
  (missing optional fields are left for Tier 2 LLM or Tier 3 manual fill)

STEP 4: If any required field is still null → add to required_fields[]
  {
    "field": "phone",
    "label": "Phone Number",
    "reason": "Required by Greenhouse",
    "source": "not_in_resume_or_profile"
  }
```

These gaps are surfaced to the user before/during fill so they can provide the value manually (Tier 3) or leave it for the LLM (Tier 2).

### Required Fields Flow

```
required_fields non-empty?
  ├── YES → Dashboard shows warning: "⚠️ 2 fields needed for Acme Corp"
  │         Chat Interface notifies: "Phone number missing for Sr Backend @ Acme"
  │         Extension: leaves missing fields blank, user fills manually
  │
  └── NO → Proceed with full auto-fill
```

### User Profile Management

Users can populate `user_profiles` via Dashboard:
- GET /api/user-profiles → fetch current profile
- PUT /api/user-profiles → update supplemental info

When user updates profile, existing applications are NOT retroactively updated.
New applications use the updated profile data.
