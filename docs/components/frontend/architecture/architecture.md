# Frontend — Next.js Dashboard

Web UI for profile management, LLM config, job review, and application history.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    NEXT.JS FRONTEND (App Router)                   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  /dashboard (main page)                                    │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Sidebar Navigation                                  │  │   │
│  │  │  ├── 📄 Profile          → /dashboard/profile        │  │   │
│  │  │  ├── 👤 User Profile     → /dashboard/user-profile   │  │   │
│  │  │  ├── 📋 Jobs             → /dashboard/jobs           │  │   │
│  │  │  ├── ⏸️  Paused          → /dashboard/paused         │  │   │
│  │  │  ├── 📊 History          → /dashboard/history        │  │   │
│  │  │  ├── 🖼️  Evidence        → /dashboard/evidence       │  │   │
│  │  │  ├── 📝 Audit Log        → /dashboard/audit          │  │   │
│  │  │  ├── ⚠️  Errors          → /dashboard/errors         │  │   │
│  │  │  ├── ⚙️  LLM Providers   → /dashboard/providers      │  │   │
│  │  │  ├── 📈 Provider Health  → /dashboard/health         │  │   │
│  │  │  ├── 🔗 Telegram         → /dashboard/telegram       │  │   │
│  │  │  ├── 💬 Discord          → /dashboard/discord        │  │   │
│  │  │  └── 🔌 Extension        → /dashboard/extension      │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Page Components                                          │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Profile (/dashboard/profile)                        │  │   │
│  │  │                                                      │  │   │
│  │  │  ┌────────────────────────────────────────────────┐  │  │   │
│  │  │  │  Upload Area                                   │  │  │   │
│  │  │  │  [Drag & Drop PDF]  or  [Browse Files]         │  │  │   │
│  │  │  │  ──────────────────────────────────────────── │  │  │   │
│  │  │  │  Current: resume_v3.pdf (uploaded 2 days ago)  │  │  │   │
│  │  │  │  Last scored: 82/100                          │  │  │   │
│  │  │  └────────────────────────────────────────────────┘  │  │   │
│  │  │                                                      │  │   │
│  │  │  ┌────────────────────────────────────────────────┐  │  │   │
│  │  │  │  JSONResume Viewer (toggle JSON/Form)          │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  Name:    [John Doe              ]             │  │  │   │
│  │  │  │  Email:   [john@email.com        ]             │  │  │   │
│  │  │  │  Phone:   [+1-555-0123           ]             │  │  │   │
│  │  │  │  Summary: [Senior backend eng with 5 yrs...  ] │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  Experience:                                   │  │  │   │
│  │  │  │  ├── Acme Corp (2022-2024): Senior Backend Eng │  │  │   │
│  │  │  │  └── Startup X (2020-2022): Software Engineer  │  │  │   │
│  │  │  └────────────────────────────────────────────────┘  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  User Profile (/dashboard/user-profile)              │  │   │
│  │  │                                                      │  │   │
│  │  │  ┌────────────────────────────────────────────────┐  │  │   │
│  │  │  │  Supplemental Personal Info                    │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  Phone:        [+1-555-0123         ]         │  │  │   │
│  │  │  │  LinkedIn:     [linkedin.com/in/johndoe]       │  │  │   │
│  │  │  │  GitHub:       [github.com/johndoe   ]         │  │  │   │
│  │  │  │  Website:      [johndoe.dev           ]         │  │  │   │
│  │  │  │  Address:      [123 Main St           ]         │  │  │   │
│  │  │  │  City:         [San Francisco         ]         │  │  │   │
│  │  │  │  State:        [CA                    ]         │  │  │   │
│  │  │  │  Country:      [USA                   ]         │  │  │   │
│  │  │  │  Postal:       [94102                 ]         │  │  │   │
│  │  │  │  DOB:          [1995-05-15            ]         │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  [Save Profile]                                │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  Used as fallback when resume is missing fields│  │  │   │
│  │  │  └────────────────────────────────────────────────┘  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Jobs (/dashboard/jobs)                              │  │   │
│  │  │                                                      │  │   │
│  │  │  ┌────────────────────────────────────────────────┐  │  │   │
│  │  │  │  Discovered Jobs (from Telegram + Manual)      │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  Job Title         Company   Score  Status       │  │  │   │
│  │  │  │  ──────────────────────────────────────────────  │  │  │   │
│  │  │  │  Senior Backend    Acme      87/100 Discovered   │  │  │   │
│  │  │  │  Full Stack Dev    Meta      72/100 Discovered   │  │  │   │
│  │  │  │  Python Engineer   Startup   91/100 Approved     │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  [✅ Approve] [❌ Reject] [📝 Edit Package]   │  │  │   │
│  │  │  └────────────────────────────────────────────────┘  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  LLM Providers (/dashboard/providers)                │  │   │
│  │  │                                                      │  │   │
│  │  │  ┌────────────────────────────────────────────────┐  │  │   │
│  │  │  │  Provider Chain (drag to reorder)              │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  1. 🟢 Gemini (free)    [Remove] [Test]       │  │  │   │
│  │  │  │     API Key: AIza...xyz   [Edit]              │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  2. 🟢 Ollama (local)  [Remove] [Test]        │  │  │   │
│  │  │  │     Endpoint: http://localhost:11434           │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  3. 🟡 Groq (free)     [Remove] [Test]        │  │  │   │
│  │  │  │     API Key: gsk_...abc   [Edit]              │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  [+ Add Provider]                              │  │  │   │
│  │  │  └────────────────────────────────────────────────┘  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  History (/dashboard/history)                        │  │   │
│  │  │                                                      │  │   │
│  │  │  ┌────────────────────────────────────────────────┐  │  │   │
│  │  │  │  Application History                           │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  Date      Job           Score  Status   Proof│  │  │   │
│  │  │  │  ──────────────────────────────────────────── │  │  │   │
│  │  │  │  Aug 20    Sr Backend   87     ✅ Filled  📷 │  │  │   │
│  │  │  │  Aug 19    Full Stack   72     ❌ Rejected ─  │  │  │   │
│  │  │  │  Aug 18    Python Dev   91     ✅ Filled  📷 │  │  │   │
│  │  │  │                                                │  │  │   │
│  │  │  │  📷 = view screenshot proof                    │  │  │   │
│  │  │  └────────────────────────────────────────────────┘  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Data Fetching

```
Frontend ←→ Backend API (FastAPI)

All data comes from /api/* endpoints.
No direct DB access from frontend.
Auth: JWT token in httpOnly cookie.
```
