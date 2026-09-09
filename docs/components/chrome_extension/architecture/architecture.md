# Chrome Extension

Client-side form filler running in the user's real browser. Indistinguishable from LastPass-style autofill — human always clicks Submit.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    CHROME EXTENSION (Manifest V3)                 │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Service Worker (background.js)                            │   │
│  │                                                            │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌────────────────┐   │   │
│  │  │  API Client  │  │  Queue Mgr   │  │  State Store   │   │   │
│  │  │              │  │              │  │                │   │   │
│  │  │  Talks to    │  │  Manages job │  │  chrome.storage │   │   │
│  │  │  FastAPI     │  │  queue from  │  │  (local state) │   │   │
│  │  │  backend     │  │  backend     │  │                │   │   │
│  │  └──────┬───────┘  └──────┬───────┘  └────────────────┘   │   │
│  │         │                 │                                │   │
│  │         └─────────────────┘                                │   │
│  │                    │                                       │   │
│  └────────────────────┼───────────────────────────────────────┘   │
│                       │                                           │
│                       │ chrome.runtime.sendMessage                 │
│                       ▼                                           │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Content Scripts (injected per page)                       │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Platform Detector                                   │  │   │
│  │  │                                                      │  │   │
│  │  │  Checks URL + DOM for platform signature:            │  │   │
│  │  │  ├── greenhouse.io → greenhouse.js                   │  │   │
│  │  │  ├── lever.co → lever.js                             │  │   │
│  │  │  ├── linkedin.com/jobs → linkedin.js                 │  │   │
│  │  │  ├── indeed.com → indeed.js                          │  │   │
│  │  │  ├── workday.com → workday.js                        │  │   │
│  │  │  └── unknown → generic.js                            │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Fill Engine (3-tier strategy)                       │  │   │
│  │  │                                                      │  │   │
│  │  │  1. Scan form fields on page                         │  │   │
│  │  │     ├── Read: label, placeholder, name, aria-label   │  │   │
│  │  │     └── Build list of all input fields               │  │   │
│  │  │                                                      │  │   │
│  │  │  2. For each field:                                  │  │   │
│  │  │     ├── Tier 1: Match against field_mappings         │  │   │
│  │  │     │   └── Found? → fill instantly (0 cost)         │  │   │
│  │  │     ├── Tier 2: No match → send to LLM              │  │   │
│  │  │     │   └── Backend calls LLM → returns value → fill │  │   │
│  │  │     └── Tier 3: No value → user fills manually       │  │   │
│  │  │                                                      │  │   │
│  │  │  3. Fill with human-like delays                      │  │   │
│  │  │     ├── focus field                                  │  │   │
│  │  │     ├── wait 300-800ms (random)                      │  │   │
│  │  │     ├── set value                                    │  │   │
│  │  │     ├── trigger input/change events                  │  │   │
│  │  │     └── move to next field                           │  │   │
│  │  │                                                      │  │   │
│  │  │  4. Record fill_details per field                    │  │   │
│  │  │     ├── label, value, filled, error, required, tier  │  │   │
│  │  │     └── POST to backend after fill completes         │  │   │
│  │  │                                                      │  │   │
│  │  │  5. Handle special fields                            │  │   │
│  │  │     ├── File upload (resume PDF)                     │  │   │
│  │  │     ├── Dropdowns (select elements)                  │  │   │
│  │  │     ├── Multi-step forms (next/prev buttons)         │  │   │
│  │  │     └── Custom textareas (cover letter)              │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Popup (popup.html)                                        │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Job Queue                                           │  │   │
│  │  │  ├── Frontend @ Stripe    [Fill] [View] [Skip]       │  │   │
│  │  │  ├── Backend @ Acme       [Fill] [View] [Skip]       │  │   │
│  │  │  ├── Full Stack @ Meta    [Fill] [View] [Skip]       │  │   │
│  │  │  └── ...                                             │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Status Bar                                         │  │   │
│  │  │  Connected to: autoapply.example.com                │  │   │
│  │  │  Queue: 5 jobs ready | 3 applied today              │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Communication Flow

```
Extension                          Backend (FastAPI)
   │                                    │
   │  GET /api/applications/ready       │
   │ ─────────────────────────────────▶ │
   │                                    │
   │  Response: [{job_id, package}]     │
   │  includes: field_mappings          │
   │ ◀───────────────────────────────── │
   │                                    │
   │  (user clicks Fill on a job)       │
   │                                    │
   │  Extension scans form fields       │
   │  Matches against field_mappings    │
   │                                    │
   │  ┌─── Tier 1: matched fields ──── fill locally (0 cost) ───┐
   │  │                                                          │
   │  │  ┌─── Tier 2: unmapped fields ──────────────────────────┐│
   │  │  │                                                      ││
   │  │  │  POST /api/extensions/{id}/fill-unmapped             ││
   │  │  │  Body: {fields: ["Why work at Stripe?", ...]}        ││
   │  │  │ ─────────────────────────────────────────────────▶   ││
   │  │  │                                                      ││
   │  │  │  Backend calls LLM with field + JD + profile context ││
   │  │  │                                                      ││
   │  │  │  Response: {values: {"Why work at Stripe?": "..."}}  ││
   │  │  │ ◀─────────────────────────────────────────────────   ││
   │  │  │                                                      ││
   │  │  │  Extension fills unmapped fields with LLM values     ││
   │  │  └──────────────────────────────────────────────────────┘│
   │  └──────────────────────────────────────────────────────────┘
   │                                    │
   │  POST /api/extensions/{id}/fill    │
   │  Body: {fill_details: [...]}       │
   │ ─────────────────────────────────▶ │
   │                                    │
   │  Response: {status: "filling"}     │
   │ ◀───────────────────────────────── │
   │                                    │
   │  (user reviews form, solves CAPTCHA)│
   │  (user clicks Submit on career page)│
   │                                    │
   │  POST /api/extensions/{id}/submit  │
   │  Body: {screenshot_url, status}    │
   │ ─────────────────────────────────▶ │
   │                                    │
   │  Response: {status: "submitted"}   │
   │ ◀───────────────────────────────── │
```

---

## Evidence Capture

After filling, before Submit:

| Evidence type | When captured | Contents |
|---|---|---|
| `screenshot` | Post-fill, pre-submit | Visual proof of filled form |
| `dom_snapshot` | Post-fill | Full DOM state of the filled page |
| `pdf` | Pre-fill | The application PDF (already generated) |

After user clicks Submit:

| Evidence type | When captured | Contents |
|---|---|---|
| `screenshot` | Post-submit | Confirmation page / success message |

All evidence linked to `applications.id`, stored in `/data/evidence/{user_id}/{app_id}/`.

---

## Isolation Model

```
Extension runs in USER'S browser
  ├── Fills like LastPass autofill (indistinguishable)
  ├── Human always clicks Submit (hard rule)
  ├── No auto-submit, ever
  └── No data sent to third parties

Backend builds field_mappings
  ├── Extension reads them, does NOT share page data back
  └── Server never sees the job site
```

---

## Platform Adapters

| Platform | Fill Strategy | Auto-Submit | Notes |
|----------|--------------|-------------|-------|
| Greenhouse | Full auto-fill (Tier 1 + 2) | No | Known field selectors |
| Lever | Full auto-fill (Tier 1 + 2) | No | Known field selectors |
| LinkedIn | Cautious fill (Tier 1 only) | No | Some fields blocked by LinkedIn |
| Indeed | Manual package only | No | SSO wall — PDF + instructions |
| Workday | Manual package only | No | Login required — PDF + instructions |
| Generic | Best-effort auto-fill (Tier 1 + 2) | No | Unknown form, LLM fills gaps |
