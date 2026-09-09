# Core Engine — Extraction Pipeline

Converts a resume PDF into structured JSONResume format.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                  EXTRACTION PIPELINE                          │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Step 1: PDF → Markdown                                │   │
│  │                                                        │   │
│  │  ┌──────────────┐     ┌──────────────────────────────┐ │   │
│  │  │  Resume PDF  │────▶│  pymupdf_rag.py              │ │   │
│  │  │  (user input)│     │  PyMuPDF → Markdown text     │ │   │
│  │  └──────────────┘     │  Handles: headings, links,   │ │   │
│  │                       │  tables, formatting           │ │   │
│  │                       └──────────────┬───────────────┘ │   │
│  │                                      │                 │   │
│  │                                      ▼                 │   │
│  │                       ┌──────────────────────────────┐ │   │
│  │                       │  Raw Markdown text           │ │   │
│  │                       └──────────────────────────────┘ │   │
│  └────────────────────────────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Step 2: Markdown → Section Extraction (per section)   │   │
│  │                                                        │   │
│  │  ┌──────────────┐     ┌──────────────────────────────┐ │   │
│  │  │  Markdown    │────▶│  pdf.py (PDFHandler)         │ │   │
│  │  │  text        │     │                              │ │   │
│  │  └──────────────┘     │  For EACH section:           │ │   │
│  │                       │  ├── Load Jinja template     │ │   │
│  │                       │  ├── Render prompt with text  │ │   │
│  │                       │  ├── Call LLM via Router     │ │   │
│  │                       │  ├── Parse JSON response     │ │   │
│  │                       │  └── Transform to JSONResume │ │   │
│  │                       └──────────────┬───────────────┘ │   │
│  │                                      │                 │   │
│  │  Sections extracted:                 ▼                 │   │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │  basics.jinja    → Name, email, phone, profiles │   │   │
│  │  │  work.jinja      → Work experience              │   │   │
│  │  │  education.jinja → Education history            │   │   │
│  │  │  skills.jinja    → Technical skills             │   │   │
│  │  │  projects.jinja  → Projects                     │   │   │
│  │  │  awards.jinja    → Awards/honors                │   │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  └────────────────────────────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Step 3: Normalize                                     │   │
│  │                                                        │   │
│  │  ┌──────────────┐     ┌──────────────────────────────┐ │   │
│  │  │  Raw LLM     │────▶│  transform.py                │ │   │
│  │  │  JSON per    │     │  Normalizes messy LLM output │ │   │
│  │  │  section     │     │  Handles: date ranges,       │ │   │
│  │  └──────────────┘     │  URL parsing, skill formats  │ │   │
│  │                       └──────────────┬───────────────┘ │   │
│  │                                      │                 │   │
│  │                                      ▼                 │   │
│  │                       ┌──────────────────────────────┐ │   │
│  │                       │  Clean JSONResume object     │ │   │
│  │                       │  (Pydantic validated)        │ │   │
│  │                       └──────────────────────────────┘ │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## Data Shape

```
Input:  Resume PDF file
Output: JSONResume object

{
  "basics": {
    "name": "John Doe",
    "email": "john@example.com",
    "phone": "+1-555-0123",
    "profiles": [{"network": "GitHub", "url": "github.com/johndoe"}],
    "location": {"city": "San Francisco", "region": "CA"},
    "summary": "Senior backend engineer..."
  },
  "work": [
    {
      "name": "Acme Corp",
      "position": "Senior Engineer",
      "startDate": "Jan 2022",
      "endDate": "Present",
      "summary": "Led microservices migration...",
      "highlights": ["Reduced latency by 40%", "Led team of 5"]
    }
  ],
  "education": [...],
  "skills": [
    {"name": "Programming Languages", "keywords": ["Python", "Go", "TypeScript"]}
  ],
  "projects": [...],
  "awards": [...]
}
```
