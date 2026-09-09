# MCP Engine

MCP stdio server exposing 7 tools for local agent mode. Each tool maps to a Backend API endpoint.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    MCP ENGINE (stdio server)                      │
│                                                                   │
│  Runs locally as a subprocess.                                    │
│  Communicates via stdin/stdout (JSON-RPC).                        │
│  Started by OpenCode/Claude when user types `/plan run job`.      │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Tool Definitions (7 tools, each maps to Backend API)      │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  TOOL 1: upload_resume                               │  │   │
│  │  │                                                      │  │   │
│  │  │  Input:  { file_path: string }                       │  │   │
│  │  │  Output: { profile_id, sections_extracted }          │  │   │
│  │  │                                                      │  │   │
│  │  │  Maps to: POST /api/profiles/upload                  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  TOOL 2: search_jobs                                 │  │   │
│  │  │                                                      │  │   │
│  │  │  Input:  { query?: string, status?: string }         │  │   │
│  │  │  Output: { jobs: [{ id, title, url, platform }] }    │  │   │
│  │  │                                                      │  │   │
│  │  │  Maps to: GET /api/jobs                   │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  TOOL 3: analyze_match                               │  │   │
│  │  │                                                      │  │   │
│  │  │  Input:  { job_id: string }                           │  │   │
│  │  │  Output: { score, strengths[], weaknesses[] }        │  │   │
│  │  │                                                      │  │   │
│  │  │  Maps to: POST /api/profiles/{id}/analyze                 │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  TOOL 4: get_package                                 │  │   │
│  │  │                                                      │  │   │
│  │  │  Input:  { application_id: string }                  │  │   │
│  │  │  Output: { pdf_url, cover_letter, field_mappings }   │  │   │
│  │  │                                                      │  │   │
│  │  │  Maps to: GET /api/applications/{id}                  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  TOOL 5: list_providers                              │  │   │
│  │  │                                                      │  │   │
│  │  │  Input:  (none)                                      │  │   │
│  │  │  Output: { providers: [{ name, status }] }           │  │   │
│  │  │                                                      │  │   │
│  │  │  Maps to: GET /api/llm/providers                     │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  TOOL 6: get_checkpoint                              │  │   │
│  │  │                                                      │  │   │
│  │  │  Input:  (none)                                      │  │   │
│  │  │  Output: { checkpoints: [{ job_id, step, state }] }  │  │   │
│  │  │                                                      │  │   │
│  │  │  Maps to: GET /api/checkpoints/pending                │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  TOOL 7: resume_pipeline                             │  │   │
│  │  │                                                      │  │   │
│  │  │  Input:  { checkpoint_id: string }                   │  │   │
│  │  │  Output: { status, next_step }                       │  │   │
│  │  │                                                      │  │   │
│  │  │  Maps to: POST /api/checkpoints/{id}/resume           │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Agent Interaction                                         │   │
│  │                                                            │   │
│  │  User (in OpenCode): "/plan run job https://greenhouse..." │   │
│  │                                                            │   │
│  │  Agent:  1. Calls search_jobs (find the job)               │   │
│  │          2. Calls analyze_match (score it)                 │   │
│  │          3. Shows score to user                             │   │
│  │          4. User says "go ahead"                            │   │
│  │          5. Calls resume_pipeline (starts pipeline)         │   │
│  │          6. Calls get_package (gets application package)    │   │
│  │          7. Shows package to user                           │   │
│  │          8. User clicks Apply in extension                  │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```
