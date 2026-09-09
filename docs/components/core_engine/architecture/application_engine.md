# Core Engine — Application Engine

Prepares application packages: field_mappings from resume + profile + JD, cover letter generation, and LLM fallback for unmapped form fields.

---

## Role in the Pipeline

After PDF generation, the application engine prepares everything the extension needs to fill a form:

```
PDF Generator ──▶ Application Engine ──▶ Application Package
                   │                       ├── optimized_resume (JSONB)
                   │                       ├── cover_letter (text)
                   │                       ├── pdf_url (PDF)
                   │                       └── field_mappings (JSONB) ← this component
                   │
                   ├── Prepares field_mappings from:
                   │   ├── optimized_resume (skills, experience, education)
                   │   ├── user_profiles (name, email, phone, URLs, visa)
                   │   └── extracted JD (salary range, role-specific context)
                   │
                   └── LLM fallback for unmapped fields at fill time
```

---

## What field_mappings Contains

All possible answers the extension might need, pre-built from existing data:

```jsonc
{
  "first_name": "John",
  "last_name": "Doe",
  "email": "john@example.com",
  "phone": "+1-555-0123",
  "linkedin_url": "linkedin.com/in/johndoe",
  "github_url": "github.com/johndoe",
  "website": "johndoe.dev",
  "years_experience": "5",
  "desired_salary": "150000",
  "work_authorization": "US Citizen",
  "cover_letter": "I'm excited about this opportunity...",
  "skills": "Python, PostgreSQL, Redis, Kafka",
  "education": "B.S. Computer Science, Stanford",
  "location": "San Francisco, CA",
  "willing_to_relocate": "Yes",
  "earliest_start_date": "2 weeks notice"
}
```

Built deterministically — zero LLM cost at this stage.

---

## The 3-Tier Fill Strategy

When the extension opens a form, it uses this strategy for each field:

### Tier 1: Deterministic match (0 cost, ~80% of fields)

Extension scans every visible input field on the page. For each field, reads: label text, placeholder, `name` attribute, `aria-label`. Matches against `field_mappings` keys.

```
"First Name" → matches "first_name" → fill "John"
"Email Address" → matches "email" → fill "john@example.com"
"Years of Experience" → matches "years_experience" → fill "5"
```

### Tier 2: LLM fallback for unmapped fields (~1 call per unknown field)

When no match exists in `field_mappings`, the extension sends the field label + context to the backend, which calls the LLM to generate a value.

```
Extension sends:
  "Form field: 'Why do you want to work at Stripe?'"
  "JD context: [requirements, company info]"
  "User profile: [skills, experience]"

Backend calls LLM → returns:
  "I'm drawn to Stripe's mission to increase..."
```

**Two execution paths:**

| Mode | Where LLM runs | Cost |
|---|---|---|
| Extension (manual open) | Backend LLM API (Gemini → Ollama → Groq → OpenRouter) | Free-tier call |
| MCP (Cursor/OpenCode) | Local LLM on user's machine | Zero |

**Fields the LLM can handle:**

| Form field | Why LLM can answer |
|---|---|
| "Why do you want to work at [Company]?" | Has JD + profile — contextual answer |
| "Describe your leadership experience" | Has work history — relevant examples |
| "What is your salary expectation?" | Has profile + JD salary range |
| "Additional information" | Has everything — decides what's relevant |
| Custom company-specific questions | Has JD requirements — synthesizes answer |

### Tier 3: Manual fill by user (0 cost)

Fields that can't be determined by matching or LLM (e.g., CAPTCHA, file upload confirmation, security questions) — user fills manually before clicking Submit.

```
Tier 1: deterministic match ──(match found)──▶ fill field
                                    │
                              (no match)
                                    │
                                    ▼
Tier 2: LLM fallback ──(value generated)──▶ fill field
                                    │
                              (no value / uncertain)
                                    │
                                    ▼
Tier 3: user fills manually ──▶ user clicks Submit
```

---

## Per-Field Fill Details (Audit Trail)

Every field attempt is recorded in `fill_details` JSONB on the `applications` table:

```jsonc
[
  {
    "label": "First Name",
    "value": "John",
    "filled": true,
    "error": null,
    "required": true,
    "tier": "deterministic"
  },
  {
    "label": "Why do you want to work at Stripe?",
    "value": "I'm drawn to Stripe's mission...",
    "filled": true,
    "error": null,
    "required": true,
    "tier": "llm_fallback"
  },
  {
    "label": "CAPTCHA",
    "value": null,
    "filled": false,
    "error": "requires_human",
    "required": true,
    "tier": "manual"
  }
]
```

This is the AutoApply pattern — exact shape to adopt.

---

## Skip Reason (Fill-Time Blockers)

When the extension opens a form and hits a blocker, `skip_reason` on the application records why:

| skip_reason | Meaning |
|---|---|
| `sso_wall` | Company uses SSO login — can't reach form |
| `captcha_required` | CAPTCHA blocks automated fill |
| `unsupported_platform` | Platform not recognized, manual package provided |
| `form_not_found` | Page loaded but no application form detected |
| `salary_mismatch` | JD salary below user minimum — skipped |
| `expired` | Posting expired before fill could start |

`skip_reason` is distinct from `fill_details`: `skip_reason` = why the application wasn't attempted; `fill_details` = what happened during the attempt.

---

## Manual Package Fallback

When Tier 1/2 can't fill (unsupported platform, SSO wall, etc.), a pre-filled manual package is always provided:

```
Manual package includes:
├── Optimized resume PDF (ready to download)
├── Cover letter text (ready to paste)
├── Pre-filled answers to likely questions (ready to copy)
└── Step-by-step instructions (how to apply manually)
```

Every job yields an actionable application — even when automation can't complete it.
