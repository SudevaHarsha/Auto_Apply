# MCP Engine — Database Scope

No tables owned. Reads and writes via Backend API.

---

## Tables Accessed

```
TABLE                MCP TOOL              READS VIA           WRITES VIA
─────────────────────────────────────────────────────────────────────────
profiles             upload_resume         POST /api/profiles/upload
                     analyze_match         POST /api/profiles/{id}/analyze
jobs                 search_jobs           GET /api/jobs
applications         get_package           GET /api/applications/{id}
llm_providers        list_providers        GET /api/llm/providers
checkpoints          get_checkpoint        GET /api/checkpoints/pending
                     resume_pipeline       POST /api/checkpoints/{id}/resume
user_profiles        (indirect via core)   GET /api/user-profiles
```

---

## Access Pattern

```
MCP engine calls Backend API for all data operations.
No direct database access.
API key auth for local agent mode.
```

---

## Tool → Endpoint Mapping

```
MCP TOOL              BACKEND API ENDPOINT         METHOD
───────────────────────────────────────────────────────────
upload_resume         /api/profiles/upload         POST
search_jobs           /api/jobs                      GET
analyze_match         /api/profiles/{id}/analyze      POST
get_package           /api/applications/{id}           GET
list_providers        /api/llm/providers           GET
get_checkpoint        /api/checkpoints/pending      GET
resume_pipeline       /api/checkpoints/{id}/resume  POST
```
