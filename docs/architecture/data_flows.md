# Data Flows

How data moves through the system for each major workflow.

---

## Flow 1: Resume Upload → Profile Created

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│  User    │────▶│ Dashboard│────▶│ FastAPI  │────▶│ PostgreSQL│
│ (upload) │     │ (Next.js)│     │ (upload) │     │ (save)   │
└──────────┘     └──────────┘     └────┬─────┘     └──────────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │ Core Engine  │
                                │              │
                                │ Extraction   │
                                │ Pipeline     │
                                │ .extract()   │
                                │              │
                                │ PyMuPDF      │
                                │ → Markdown   │
                                │ → LLM/section│
                                │ → JSONResume │
                                └──────┬───────┘
                                       │
                                       ▼
                                ┌──────────────┐
                                │ PostgreSQL   │
                                │ profiles     │
                                │ (JSONB data) │
                                └──────────────┘
```

---

## Flow 2: Job Discovery → Application Ready

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Telegram │────▶│ Discovery│────▶│ FastAPI  │
│ Bot API  │     │ Service  │     │ (save)   │
└──────────┘     └──────────┘     └────┬─────┘
                    │                   │
                    │ 1. URL extracted  │
                    │ 2. Title/company  │
                    │    from text      │  (zero cost)
                    ▼                   │
             ┌──────────────┐          │
             │ Message text │          │
             │ context      │          │
             │ (free parse) │          │
             └──────────────┘          │
                                       ▼
                                ┌──────────────┐
                                │ PostgreSQL   │
                                │ jobs         │
                                │ status:      │
                                │ discovered   │
                                │ source:      │
                                │ telegram     │
                                └──────┬───────┘
                                       │
                                       ▼ (5-door cascade)
                  ┌────────────────────────────────────────┐
                  │  Door 0: classify URL (0 tokens)       │
                  │  ┌──────┐  ┌───────┐  ┌────────────┐  │
                  │  │GH/   │  │Workday│  │ Generic    │  │
                  │  │Lever │  │       │  │            │  │
                  │  └──┬───┘  └──┬────┘  └─────┬──────┘  │
                  └─────┼────────┼──────────────┼─────────┘
                        │        │              │
                        ▼        ▼              ▼
                  ┌──────────┐ ┌──────────┐ ┌──────────┐
                  │ Door 1:  │ │ Door 2:  │ │ Door 2:  │
                  │ ATS API  │ │ JSON-LD  │ │ JSON-LD  │
                  │ 0 tokens │ │ 0 tokens │ │ 0 tokens │
                  └────┬─────┘ └────┬─────┘ └────┬─────┘
                       │            │            │
                       └──────┬─────┘────────────┘
                              │
                              ▼ (if Door 1/2 incomplete)
                  ┌──────────────────────────────────────┐
                  │  Door 3: text strip (0 tokens)       │
                  │  Reduce HTML to posting text only     │
                  └──────────────┬───────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────────┐
                  │  Door 4: LLM parse (~1 free call)    │
                  │  Fill structured JD Pydantic schema   │
                  └──────────────┬───────────────────────┘
                                 │
                                 ▼
                  ┌──────────────────────────────────────┐
                  │  Door 5: gap-fill (0-1 calls)        │
                  │  Fill only missing critical fields    │
                  └──────────────┬───────────────────────┘
                                 │
                                 ▼
               ┌─────────────────────────────────────────┐
               │  Structured JD extracted                │
               │  (every job stored, regardless of match) │
               └─────────────────┬───────────────────────┘
                                 │
                                 ▼
               ┌─────────────────────────────────────────┐
               │  Snapshot & Freshness                   │
               │  INSERT job_snapshots (content_hash)    │
               │  jobs: current_snapshot_id +            │
               │  freshness FSM: fresh|stale|expired     │
               │  Search-tier  72h → stale               │
               │  Package-tier 6h → expired:             │
               │    blocks fill (skip_reason)            │
               └─────────────────┬───────────────────────┘
                                 │
                                 ▼
               ┌─────────────────────────────────────────┐
               │  Rubric Generator                       │
               │  JD requirements → scoring rubric       │
               └─────────────────┬───────────────────────┘
                                 │
                                 ▼
               ┌─────────────────────────────────────────┐
               │  Scorer                                 │
               │  Profile vs rubric → Score + Evidence   │
               └─────────────────┬───────────────────────┘
                                 │
                       ┌────────┴────────┐
                       │ Score >= 85?    │
                       └────────┬────────┘
                         YES    │   NO
                          │     │   │
                          │     │   ▼
                          │     │  ┌──────────────────────┐
                          │     │  │ Optimizer            │
                          │     │  │ LLM rewrites profile │
                          │     │  │ → better score       │
                          │     │  └──────────┬───────────┘
                          │     │             │ (re-score loop)
                          │     │             ▼ back to Scorer
                          │     │
                          ▼     ▼
               ┌─────────────────────────────────────────┐
               │  PDF Generator                          │
               │  JSONResume → HTML/CSS → PDF (Weasy)    │
               └─────────────────┬───────────────────────┘
                                 │
                                 ▼
               ┌─────────────────────────────────────────┐
               │  Application Package                    │
               │  ├── PDF                                │
               │  ├── Cover                              │
               │  ├── Fields                             │
               │  └── URL                                │
               └─────────────────┬───────────────────────┘
                                 │
                                 ▼
               ┌─────────────────────────────────────────┐
               │  PostgreSQL                             │
               │  applications                           │
               │  status: created                        │
                │  (skip_reason = NULL if fill succeeded)        │
                │  (skip_reason = reason if fill was blocked)    │
               └─────────────────────────────────────────┘
```

---

## Flow 3: Discord Discovery → Job Created

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Discord  │────▶│ Discord  │────▶│ FastAPI  │────▶│ PostgreSQL│
│ Bot API  │     │ Service  │     │ (save)   │     │ jobs     │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
                     │
                     │ URL extracted from message
                     ▼
              ┌──────────────┐
              │ JD Extractor │
              │              │
              │ HTTP GET     │
              │ → parse HTML │
              │ → structured │
              │   JD (JSON)  │
              └──────┬───────┘
                     │
                     ▼
              (same as Telegram flow:
               Rubric → Score → Optimize → Package)
```

---

## Flow 4: Extension Fill → Submission

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Extension│────▶│ FastAPI  │────▶│ PostgreSQL│
│ (poll)   │     │ GET /api │     │applications│
└────┬─────┘     │ packages │     └──────────┘
     │           └──────────┘
     │ get package (field_mappings)
     ▼
┌──────────┐
│ Extension│
│ popup    │
│          │
│ [Fill]   │
│ button   │
└────┬─────┘
     │
     ▼
┌──────────┐     ┌──────────┐
│ New Tab  │────▶│ ATS Site │
│ (job URL)│     │(Greenhse,│
└──────────┘     │ LinkedIn)│
                 └────┬─────┘
                      │
                      ▼
              ┌──────────────┐
              │ Fill Engine  │
              │              │
              │ Scan form    │
              │ fields →     │
              │              │
              │ TIER 1:      │
              │ match against│
              │ field_mappings ── match → fill (0 cost)
              │    │
              │    │ no match
              │    ▼
              │ TIER 2:      │
              │ send label + │
              │ JD + profile │
              │ to backend → │
              │ LLM generates│
              │ value → fill │
              │    │
              │    │ no value
              │    ▼
              │ TIER 3:      │
              │ user fills   │
              │ manually     │
              │ (CAPTCHA etc)│
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐     ┌──────────┐
              │ Fill Details │────▶│ FastAPI  │
              │ per-field    │     │ POST     │
              │ {label,value,│     │ fill_details│
              │  filled,err, │     └──────────┘
              │  tier}       │
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐
              │ User         │
              │ Reviews →    │
              │ Solves CAPTCHA →
              │ Clicks Submit│
              └──────┬───────┘
                     │
                     ▼
              ┌──────────────┐     ┌──────────┐
              │ Extension    │────▶│ FastAPI  │
              │ captures     │     │ POST     │
              │ screenshot → │     │ /submit  │
              │ reports back │     └──────────┘
              └──────────────┘
```

---

## Flow 5: Provider Failover

```
                    ┌──────────────┐
                    │ LLM Request  │
                    └──────┬───────┘
                           │
                           ▼
                    ┌──────────────┐
                    │ Try: Gemini  │──── Success ───▶ Return
                    │ Free         │
                    └──────┬───────┘
                           │ 429 / Error
                           ▼
                    ┌──────────────┐
                    │ Try: Ollama  │──── Success ───▶ Return
                    │ Local        │
                    └──────┬───────┘
                           │ Unavailable
                           ▼
                    ┌──────────────┐
                    │ Try: Groq    │──── Success ───▶ Return
                    │ Free         │
                    └──────┬───────┘
                           │ 429 / Error
                           ▼
                    ┌──────────────┐
                    │ Try:         │──── Success ───▶ Return
                    │ OpenRouter   │
                    │ Free         │
                    └──────┬───────┘
                           │ All failed
                           ▼
                    ┌──────────────┐
                    │ Save         │
                    │ Checkpoint   │
                    │              │
                    │ Notify user: │
                    │ "Switch keys │
                    │  or wait"    │
                    └──────────────┘
```

---

## Flow 6: Checkpoint & Resume

```
Pipeline Step 1          Step 2          Step 3
┌────────────┐      ┌────────────┐  ┌────────────┐
│ Extract JD │─────▶│   Score    │─▶│  Optimize  │
│            │      │            │  │            │
│ Status:    │      │ Status:    │  │ Status:    │
│ completed  │      │ RUNNING    │  │ pending    │
└────────────┘      └─────┬──────┘  └────────────┘
                          │
                          │ CRASH / Provider exhausted
                          ▼
                   ┌────────────┐
                   │ Checkpoint │
                   │ saved to   │
                   │ PostgreSQL │
                   │            │
                   │ step: scoring│
                   │ input: {..}│
                   │ output: null│
                   └────────────┘
                          │
                          │ ... time passes ...
                          │
                          ▼
                   ┌────────────┐
                   │ Resume from│
                   │ checkpoint │
                   │            │
                   │ Re-run     │
                   │ step: scoring│
                   └────────────┘
```
