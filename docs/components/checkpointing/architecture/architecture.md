# Checkpointing — State Persistence

Save and resume pipeline state when LLM providers fail or user pauses.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    CHECKPOINT SERVICE                              │
│                                                                   │
│  Every pipeline step saves state to the checkpoints table.        │
│  If something fails, resume from last good checkpoint.            │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Pipeline Steps (with checkpoint save after each)          │   │
│  │                                                            │   │
│  │  Step 1: JD Extraction                                    │   │
│  │  ├── Fetch career page                                    │   │
│  │  ├── Parse + LLM extract                                  │   │
│  │  └── CHECKPOINT → save structured_jd                      │   │
│  │                                                            │   │
│  │  Step 2: Rubric Generation                                │   │
│  │  ├── Generate role.json + criteria.jinja                  │   │
│  │  └── CHECKPOINT → save rubric_config                      │   │
│  │                                                            │   │
│  │  Step 3: Scoring                                          │   │
│  │  ├── Score profile against rubric                         │   │
│  │  └── CHECKPOINT → save evaluation_result                  │   │
│  │                                                            │   │
│  │  Step 4: Optimization (if needed)                         │   │
│  │  ├── Rewrite sections                                     │   │
│  │  ├── Re-score                                             │   │
│  │  └── CHECKPOINT → save optimized_resume + new_score       │   │
│  │                                                            │   │
│  │  Step 5: Package Generation                               │   │
│  │  ├── Generate PDF                                         │   │
│  │  ├── Build field mappings                                 │   │
│  │  └── CHECKPOINT → save package (ready for extension)      │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Resume Flow                                              │   │
│  │                                                            │   │
│  │  Failure at Step 3 (scoring):                              │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  checkpoints table:                                  │  │   │
│  │  │  ├── step: "scoring"                                 │  │   │
│  │  │  ├── pipeline_state: {                               │  │   │
│  │  │  │     structured_jd: {...},  (from Step 1)         │  │   │
│  │  │  │     rubric_config: {...}   (from Step 2)         │  │   │
│  │  │  │   }                                               │  │   │
│  │  │  └── error_message: "Gemini rate limited"            │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  Resume:                                                   │   │
│  │  ├── Read checkpoint from DB                               │   │
│  │  ├── Skip Steps 1 + 2 (already saved)                     │   │
│  │  └── Restart at Step 3 with saved state                    │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  User-Triggered Resume (via Dashboard)                     │   │
│  │                                                            │   │
│  │  Dashboard shows:                                          │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Paused Applications                                │  │   │
│  │  │  ├── Sr Backend @ Acme — paused at scoring (Aug 20) │  │   │
│  │  │  │   Error: Gemini rate limited                     │  │   │
│  │  │  │   [Resume] [Discard]                             │  │   │
│  │  │  │                                                  │  │   │
│  │  │  ├── Full Stack @ Meta — paused at PDF gen (Aug 19) │  │   │
│  │  │  │   Error: Provider timeout                        │  │   │
│  │  │  │   [Resume] [Discard]                             │  │   │
│  │  │  └──────────────────────────────────────────────────┘  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Cleanup Policy

```
Completed checkpoints: deleted after 7 days
Failed checkpoints: kept for 30 days (for debugging)
Manual discard: immediate deletion
```
