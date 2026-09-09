# Core Engine — PDF Generator

Converts an optimized JSONResume into an ATS-friendly PDF.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                      PDF GENERATOR                            │
│                                                               │
│  INPUT: Optimized JSONResume object                          │
│                                                               │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Step 1: JSONResume → HTML                             │   │
│  │                                                        │   │
│  │  ┌──────────────┐     ┌──────────────────────────────┐ │   │
│  │  │  JSONResume  │────▶│  Jinja2 Template             │ │   │
│  │  │  (optimized) │     │                              │ │   │
│  │  └──────────────┘     │  ATS-friendly HTML/CSS:      │ │   │
│  │                       │  ├── Clean layout             │ │   │
│  │                       │  ├── No tables/columns        │ │   │
│  │                       │  ├── Standard fonts           │ │   │
│  │                       │  ├── Clear section headers    │ │   │
│  │                       │  ├── Keywords preserved       │ │   │
│  │                       │  └── No graphics/images       │ │   │
│  │                       └──────────────┬───────────────┘ │   │
│  │                                      │                 │   │
│  │                                      ▼                 │   │
│  │                       ┌──────────────────────────────┐ │   │
│  │                       │  HTML document               │ │   │
│  │                       └──────────────────────────────┘ │   │
│  └────────────────────────────────────────────────────────┘   │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  Step 2: HTML → PDF                                    │   │
│  │                                                        │   │
│  │  ┌──────────────┐     ┌──────────────────────────────┐ │   │
│  │  │  HTML        │────▶│  WeasyPrint                  │ │   │
│  │  └──────────────┘     │                              │ │   │
│  │                       │  Renders HTML → PDF:          │ │   │
│  │                       │  ├── Page layout              │ │   │
│  │                       │  ├── Font embedding           │ │   │
│  │                       │  ├── Margin handling          │ │   │
│  │                       │  └── Print optimization       │ │   │
│  │                       └──────────────┬───────────────┘ │   │
│  │                                      │                 │   │
│  │                                      ▼                 │   │
│  │                       ┌──────────────────────────────┐ │   │
│  │                       │  PDF file                    │ │   │
│  │                       └──────────────────────────────┘ │   │
│  └────────────────────────────────────────────────────────┘   │
│                                                               │
│  OUTPUT:                                                      │
│  ┌────────────────────────────────────────────────────────┐   │
│  │  resume_john_doe_backend_acme.pdf                      │   │
│  │                                                        │   │
│  │  File saved to: /data/evidence/{user_id}/{app_id}/application.pdf │   │
│  │  URL returned for: application package / download      │   │
│  └────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────┘
```

---

## ATS-Friendly Design Rules

```
DO:                              DON'T:
├── Use standard fonts           ├── Use custom/web fonts
├── Use single-column layout    ├── Use multi-column layouts
├── Use clear section headers   ├── Use fancy graphics
├── Use bullet points           ├── Use tables for layout
├── Keep keywords from JD       ├── Remove relevant keywords
├── Use simple formatting       ├── Use text boxes/overlays
└── Export as text-based PDF    └── Export as image-based PDF
```
