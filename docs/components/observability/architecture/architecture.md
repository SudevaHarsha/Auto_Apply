# Observability — Tracing and Logging

Lightweight observability for debugging pipeline failures.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    OBSERVABILITY STACK                             │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Structured Logging (JSON logs)                           │   │
│  │                                                            │   │
│  │  Every service writes structured JSON logs:                │   │
│  │  {                                                        │   │
│  │    "timestamp": "2026-08-20T14:32:01Z",                   │   │
│  │    "level": "info",                                       │   │
│  │    "service": "core_engine",                              │   │
│  │    "user_id": "abc-123",                                  │   │
│  │    "job_id": "def-456",                                   │   │
│  │    "step": "scoring",                                     │   │
│  │    "provider": "gemini",                                  │   │
│  │    "latency_ms": 3420,                                    │   │
│  │    "tokens_used": 1250,                                   │   │
│  │    "score": 87,                                           │   │
│  │    "event": "scoring_complete"                            │   │
│  │  }                                                        │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Pipeline Tracing                                          │   │
│  │                                                            │   │
│  │  Each job gets a trace_id that follows it through:         │   │
│  │                                                            │   │
│  │  trace_id: abc-123-def-456                                 │   │
│  │  ├── [14:30:01] telegram.discover → job created            │   │
│  │  ├── [14:30:02] jd_extractor.fetch → greenho.../jobs/12345 │   │
│  │  ├── [14:30:05] jd_extractor.parse → structured_jd         │   │
│  │  ├── [14:30:06] rubric_generator.generate → role.json      │   │
│  │  ├── [14:30:08] scorer.evaluate → score: 87/100            │   │
│  │  ├── [14:30:09] package.build → pdf generated              │   │
│  │  └── [14:30:10] package.ready → sent to extension          │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Provider Health Dashboard                                 │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  Provider    Status    Avg Latency   Success Rate   │  │   │
│  │  │  ────────────────────────────────────────────────── │  │   │
│  │  │  Gemini      CLOSED    3.2s          94%            │  │   │
│  │  │  Ollama      CLOSED    8.1s          99%            │  │   │
│  │  │  Groq        OPEN      -             0% (blocked)   │  │   │
│  │  │  OpenRouter  HALF_OPEN 5.7s          67%            │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Error Categories                                          │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  category              action           notify user  │  │   │
│  │  │  ────────────────────────────────────────────────── │  │   │
│  │  │  provider_rate_limit   retry next       no           │  │   │
│  │  │  provider_error        skip + try next  no           │  │   │
│  │  │  extraction_failure    checkpoint       yes          │  │   │
│  │  │  scoring_failure       checkpoint       yes          │  │   │
│  │  │  all_providers_down    checkpoint       yes          │  │   │
│  │  │  invalid_resume        reject upload    yes          │  │   │
│  │  │  career_page_404       mark failed      no           │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Storage

```
Logs: stdout → collected by host (or Supabase log drain)
Trace data: stored in checkpoints.pipeline_state JSONB
Metrics: computed from application status counts (no extra infra)
```
