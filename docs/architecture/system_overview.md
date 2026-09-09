# System Overview

High-level view of all AutoApply components and how they connect.

---

## Component Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            CLIENT LAYER                                  │
│                                                                         │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────────────────┐  │
│  │   Next.js     │   │   Chrome      │   │   Local IDE               │  │
│  │   Dashboard   │   │   Extension   │   │   (Cursor / OpenCode)     │  │
│  │   :3000       │   │   (User's     │   │   via MCP stdio           │  │
│  │               │   │    Browser)   │   │                           │  │
│  └───────┬───────┘   └───────┬───────┘   └─────────────┬─────────────┘  │
└──────────┼───────────────────┼─────────────────────────┼────────────────┘
           │ REST              │ REST                    │ stdio
           │                   │                         │
┌──────────┼───────────────────┼─────────────────────────┼────────────────┐
│          ▼                   ▼                         ▼                │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                        BACKEND                                   │   │
│  │                                                                  │   │
│  │   ┌──────────────┐    ┌──────────────┐                           │   │
│  │   │   FastAPI     │◄──►│  MCP Engine  │                           │   │
│  │   │   REST API    │    │  (tools)     │                           │   │
│  │   │   :8000       │    │              │                           │   │
│  │   └──────┬───────┘    └──────┬───────┘                           │   │
│  │          │                   │                                    │   │
│  │   ┌──────┴───────────────────┴──────────────────────────────┐    │   │
│  │   │                    CORE ENGINE                            │   │   │
│  │   │                                                           │   │   │
│  │   │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐   │   │   │
│  │   │  │ Extraction │  │  Scoring   │  │   Optimization     │   │   │   │
│  │   │  └────────────┘  └────────────┘  └────────────────────┘   │   │   │
│  │   │  ┌────────────┐  ┌────────────┐  ┌────────────────────┐   │   │   │
│  │   │  │ JD Extract │  │  Rubric    │  │   PDF Generator    │   │   │   │
│  │   │  └────────────┘  │  Generator │  └────────────────────┘   │   │   │
│  │   │                  └────────────┘                            │   │   │
│  │   │  ┌─────────────────────────────────────────────────────┐   │   │   │
│  │   │  │           Application Engine (JD+Profile → fields)  │   │   │   │
│  │   │  └─────────────────────────────────────────────────────┘   │   │   │
│  │   │  ┌─────────────────────────────────────────────────────┐   │   │   │
│  │   │  │            LLM Router (Failover Chain)              │   │   │   │
│  │   │  │         Gemini -> Ollama -> Groq -> OpenRouter      │   │   │   │
│  │   │  └─────────────────────────────────────────────────────┘   │   │   │
│  │   └───────────────────────────────────────────────────────────┘   │   │
│  │                                                                   │   │
│  │   ┌───────────────────────────────────────────────────────────┐   │   │
│  │   │                     SERVICES                              │   │   │
│  │   │                                                           │   │   │
│  │   │  ┌───────────┐  ┌───────────┐  ┌──────────────────────┐   │   │   │
│  │   │  │ Telegram  │  │  Discord  │  │   Checkpoint Mgr     │   │   │   │
│  │   │  │ Discovery │  │ Discovery │  │                      │   │   │   │
│  │   │  └───────────┘  └───────────┘  └──────────────────────┘   │   │   │
│  │   │  ┌───────────┐  ┌───────────┐  ┌──────────────────────┐   │   │   │
│  │   │  │ Evidence  │  │   Audit   │  │   Provider Health    │   │   │   │
│  │   │  │ Collector │  │  Logger   │  │   Monitor            │   │   │   │
│  │   │  └───────────┘  └───────────┘  └──────────────────────┘   │   │   │
│  │   └───────────────────────────────────────────────────────────┘   │   │
│  └──────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  ┌──────────────────────────────────────────────────────────────────┐   │
│  │                        DATA LAYER                                │   │
│  │                                                                  │   │
│  │   ┌────────────────────┐       ┌────────────────────┐            │   │
│  │   │    PostgreSQL      │       │   File Storage     │            │   │
│  │   │    (RLS enabled)   │       │   (evidence, PDFs) │            │   │
│  │   └────────────────────┘       └────────────────────┘            │   │
│  └──────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Three Access Modes

```
MODE 1: Local Agent (MCP via stdio)
+--------------------------------------+
|  Cursor / OpenCode                   |
|  +-- MCP Server (stdio)             |
|  +-- Core Engine (Python)           |
|  +-- Ollama (local LLM)            |
|  +-- Local PostgreSQL (optional)    |
|                                      |
|  Token Cost: Charged to IDE host    |
+--------------------------------------+

MODE 2: Chat Interface (Bot + Agent)
+--------------------------------------+
|  Web UI or Discord                   |
|  +-- Bot Mode (regex, zero tokens)  |
|  +-- Agent Mode (LLM, flexible)     |
|                                      |
|  Token Cost: Zero (Bot) / High (Agent)|
+--------------------------------------+

MODE 3: Dashboard (REST Endpoints)
+--------------------------------------+
|  Next.js Dashboard                   |
|  +-- Buttons map to FastAPI routes   |
|  +-- No intent parsing              |
|  +-- Direct API calls               |
|                                      |
|  Token Cost: Minimum (execution only)|
+--------------------------------------+
```

---

## Mode Details

### Mode 1: Local Agent (MCP via stdio)
- Exposes all pipeline tools natively to Cursor or OpenCode
- Host IDE's AI reads natural language prompts and executes MCP tools
- Token Cost: Charged to IDE host's API/keys

### Mode 2: Chat Interface (Web UI & Discord)
Two switchable sub-modes:
1. Bot Mode (Default): Keyword/regex parsing, zero token overhead
2. Agent Mode: LLM parses natural language, decides which tools to call

### Mode 3: Dashboard (REST Endpoints)
- Dashboard buttons map directly to FastAPI REST routes
- No conversational intent parsing
- Token Cost: Minimum (only for actual LLM execution)

---

## Component Table

| Component | Purpose | Tables Owned |
|-----------|---------|-------------|
| auth | User identity, API keys, settings | users, api_keys, settings, user_profiles |
| chat_interface | User interaction (Bot + Agent modes) | (stateless, reads settings) |
| backend_api | REST endpoints, request routing | (stateless, no ownership) |
| core_engine | Pipeline orchestration, LLM calls | profiles, jobs, applications, pipeline_runs, job_snapshots |
| llm_router | Provider chain, failover, token tracking | llm_providers, provider_usage, rate_limit_state |
| discovery | Telegram bot, URL extraction | telegram_connections, telegram_messages |
| discord | Discord bot, notifications | discord_connections, discord_messages |
| chrome_extension | Form filling, screenshot capture | evidence |
| observability | Audit logs, error tracking | audit_logs, error_logs |
| checkpointing | Save/resume pipeline state | checkpoints |
