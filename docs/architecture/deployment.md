# Deployment Architecture

How the system is deployed across environments.

---

## Cloud Deployment (Primary)

```
┌─────────────────────────────────────────────────────────┐
│                     VPS / Docker                         │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │                 Docker Compose                      │  │
│  │                                                     │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌────────────┐  │  │
│  │  │  Next.js    │  │  FastAPI    │  │ PostgreSQL │  │  │
│  │  │  :3000      │  │  :8000      │  │  :5432     │  │  │
│  │  │  (frontend) │  │  (backend)  │  │  (data)    │  │  │
│  │  └─────────────┘  └─────────────┘  └────────────┘  │  │
│  │                                                     │  │
│  │  ┌─────────────┐  ┌─────────────┐                  │  │
│  │  │  Telegram   │  │  Discord    │                  │  │
│  │  │  Bot Svc    │  │  Bot Svc    │                  │  │
│  │  │  (per user) │  │  (per user) │                  │  │
│  │  └─────────────┘  └─────────────┘                  │  │
│  │                                                     │  │
│  │  ┌─────────────┐  (optional)                       │  │
│  │  │  Ollama     │                                   │  │
│  │  │  :11434     │                                   │  │
│  │  │  (local LLM)│                                   │  │
│  │  └─────────────┘                                   │  │
│  │                                                     │  │
│  │  ┌─────────────────────────────────────────────┐    │  │
│  │  │  /data/evidence/                            │    │  │
│  │  │  ├── screenshots/                           │    │  │
│  │  │  ├── pdfs/                                  │    │  │
│  │  │  └── dom_snapshots/                         │    │  │
│  │  └─────────────────────────────────────────────┘    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  Public IP: x.x.x.x                                     │
│  ├── :3000  → Next.js Dashboard                         │
│  └── :8000  → FastAPI REST API + MCP HTTP                │
└─────────────────────────────────────────────────────────┘

                    ▲
                    │ HTTPS
                    │
┌───────────────────┼─────────────────────────────────────┐
│  User's Machine   │                                      │
│                   │                                      │
│  ┌────────────────┴──────────────────────────────────┐  │
│  │  Chrome Browser                                    │  │
│  │  ├── Extension connects to :8000                   │  │
│  │  ├── User logged into ATS sites                    │  │
│  │  └── Fills forms in real browser                   │  │
│  └───────────────────────────────────────────────────┘  │
│                                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  Telegram App (user's phone/desktop)              │  │
│  │  ├── Bot added to job-seeking groups              │  │
│  │  └── Messages forwarded to backend                │  │
│  └───────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## Local Deployment (Secondary)

> **Subset only:** This diagram covers the local-agent mode — MCP tools → Core Engine with Ollama, PostgreSQL optional (caching). Cloud-only services (FastAPI REST, Next.js Dashboard, Telegram/Discord bots, evidence collection) are not part of local mode; run the cloud stack (below) for those.

```
┌──────────────────────────────────────────────────────────┐
│  User's Machine                                          │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Cursor / OpenCode / Terminal                      │  │
│  │                                                    │  │
│  │  ┌──────────────────────────────────────────────┐  │  │
│  │  │  MCP Server (stdio)                          │  │  │
│  │  │                                              │  │  │
│  │  │  ├── Core Engine (Python)                    │  │  │
│  │  │  │   ├── Extraction                          │  │  │
│  │  │  │   ├── Scoring                             │  │  │
│  │  │  │   ├── Optimization                        │  │  │
│  │  │  │   └── PDF Generation                      │  │  │
│  │  │  │                                           │  │  │
│  │  │  └── LLM Router                              │  │  │
│  │  │      └── Ollama (local)                      │  │  │
│  │  └──────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  Ollama :11434                                     │  │
│  │  └── gemma4:latest / gemma3:12b                    │  │
│  └────────────────────────────────────────────────────┘  │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │  PostgreSQL :5432 (optional, for caching)          │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## Docker Compose (Cloud)

```yaml
services:
  nextjs:
    build: ./frontend
    ports: ["3000:3000"]
    depends_on: [api]

  api:
    build: ./backend
    ports: ["8000:8000"]
    depends_on: [db]
    env_file: .env

  db:
    image: postgres:16
    ports: ["5432:5432"]
    volumes: [pgdata:/var/lib/postgresql/data]

  telegram:
    build: ./backend
    # Runs telegram bot service separately

  discord:
    build: ./backend
    # Runs discord bot service separately

volumes:
  pgdata:
```

---

## Network Diagram

```
Internet
    │
    │ HTTPS (:443)
    ▼
┌───────────────────────────────┐
│  Reverse Proxy (Nginx/Caddy)  │
│  ├── /        → :3000 (Next) │
│  └── /api     → :8000 (Fast) │
└───────────────┬───────────────┘
                │
    ┌───────────┴───────────┐
    │                       │
    ▼                       ▼
┌─────────┐          ┌─────────┐
│ Next.js │          │ FastAPI │
│ :3000   │          │ :8000   │
└─────────┘          └────┬────┘
                          │
                    ┌─────┴─────┐
                    │           │
                    ▼           ▼
             ┌──────────┐
             │PostgreSQL│
             │ :5432    │
             └──────────┘

External APIs (outbound only):
├── api.telegram.org (Bot API)
├── generativelanguage.googleapis.com (Gemini)
├── api.groq.com (Groq)
├── openrouter.ai (OpenRouter)
├── greenhouse.io, lever.co (JD scraping)
└── github.com (API, optional)
```
