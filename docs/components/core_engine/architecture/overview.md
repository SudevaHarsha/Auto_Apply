# Core Engine — Overview

The Core Engine contains all LLM-powered logic. It has 8 components that work together.

---

## Component Map

```
┌─────────────────────────────────────────────────────────────────┐
│                        CORE ENGINE                               │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │  Extraction  │   │   Scoring    │   │    Optimization      │ │
│  │  Pipeline    │   │   Engine     │   │    Engine            │ │
│  │              │   │              │   │                      │ │
│  │  PDF → JSON  │   │  JSON → Score│   │  Score → Rewrite →   │ │
│  │  Resume      │   │  + Evidence  │   │  Better Score        │ │
│  └──────────────┘   └──────────────┘   └──────────────────────┘ │
│                                                                  │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐ │
│  │  JD          │   │  Rubric      │   │   Application        │ │
│  │  Extractor   │   │  Generator   │   │   Engine             │ │
│  │              │   │              │   │                      │ │
│  │  URL → JD    │   │  JD → Role   │   │  JD+Profile →        │ │
│  │  (5 doors)   │   │  Definition  │   │  field_mappings +    │ │
│  │  (JSON)      │   │              │   │  LLM fallback        │ │
│  └──────────────┘   └──────────────┘   └──────────┬───────────┘ │
│                                                   │             │
│  ┌──────────────┐   ┌─────────────────────────────┴──────────┐ │
│  │  PDF         │   │                                        │ │
│  │  Generator   │   │  (extension consumes field_mappings,   │ │
│  │              │   │   reports fill_details back)           │ │
│  │  JSON→ PDF   │   │                                        │ │
│  └──────────────┘   └────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
         │              │              │              │
         ▼              ▼              ▼              ▼
┌─────────────────────────────────────────────────────────────────┐
│                      LLM ROUTER                                  │
│              Gemini → Ollama → Groq → OpenRouter                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## Source vs New

| Component | Source | Built By |
|-----------|--------|----------|
| Extraction Pipeline | `hiring-agent-main` (pdf.py, pymupdf_rag.py) | Import as-is |
| Scoring Engine | `hiring-agent-main` (evaluator.py, roles.py) | Import as-is |
| JD Extractor | **New** | AutoApply |
| Rubric Generator | **New** | AutoApply |
| Optimization Engine | **New** | AutoApply |
| PDF Generator | **New** | AutoApply |
| Application Engine | **New** | AutoApply |
| LLM Router | **New** | AutoApply |

---

## How They Chain Together

```
Job Discovery finds a URL (+ free context from message text)
        │
        ▼
┌──────────────┐
│ JD Extractor │──── 5-door cascade (API → JSON-LD → strip → LLM)
│ (5 doors)    │     Most finish at Door 1/2 (zero tokens)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Rubric       │──── Converts requirements into scoring rubric
│ Generator    │     (dynamic Role definition)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Extraction   │──── Extracts user's profile from their resume PDF
│ Pipeline     │     (JSONResume format)
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Scoring      │──── Scores profile against the rubric
│ Engine       │     Returns: score + evidence + strengths/weaknesses
└──────┬───────┘
       │
       │ IF score < threshold:
       ▼
┌──────────────┐
│ Optimization │──── LLM rewrites profile sections to improve score
│ Engine       │     Constraint: never fabricate experiences
└──────┬───────┘
       │
       ▼ (re-score, loop until done)
┌──────────────┐
│ PDF          │──── Converts optimized JSONResume to ATS-friendly PDF
│ Generator    │     HTML/CSS template → WeasyPrint → PDF
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Application  │──── Prepares field_mappings from optimized resume,
│ Engine       │     user_profiles, and JD
└──────┬───────┘     Provides LLM fallback for unmapped fields at fill time
       │
       ▼
┌──────────────┐
│ Extension    │──── Tier 1: deterministic match (0 cost)
│ (client-side)│     Tier 2: LLM fallback (unmapped fields)
└──────────────┘     Tier 3: user fills manually
                     Human always clicks Submit
```

Every job is extracted and stored regardless of user match. Jobs that aren't shown are left in `jobs.status` (there is no `jobs.skip_reason`); `applications.skip_reason` records why a fill was blocked (SSO wall, CAPTCHA, unsupported platform, `expired`).
