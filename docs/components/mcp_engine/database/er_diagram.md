# MCP Engine — ER Diagram

Entity-Relationship diagram showing all tables accessed by the MCP engine.

---

## Diagram

```
┌─────────────────────────────────────────────────┐
│              MCP ENGINE TOOLS                    │
├─────────────────────────────────────────────────┤
│                                                  │
│  upload_resume ─────> profiles                   │
│  search_jobs ───────> jobs                       │
│  analyze_match ─────> jobs, llm_providers        │
│  get_package ───────> applications               │
│  list_providers ────> llm_providers              │
│  get_checkpoint ────> checkpoints                │
│  resume_pipeline ───> checkpoints, pipeline_runs │
│                                                  │
└─────────────────────────────────────────────────┘
         │
         │ reads via
         ▼
┌─────────────────┐
│   Backend API   │
├─────────────────┤
│  ALL 20 tables  │
└─────────────────┘
```

---

## Access Pattern

```
MCP engine reads 6 tables via Backend API
Local agent connects via stdio (no HTTP, no auth needed)
Cloud mode: API key auth (Future — not implemented yet)
```
