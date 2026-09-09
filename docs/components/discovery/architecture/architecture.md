# Discovery — Telegram Bot Service

Listens to Telegram groups/channels for job postings. Extracts URLs and free context from message text. Every job is stored and extracted regardless of user match.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    TELEGRAM DISCOVERY SERVICE                     │
│                                                                   │
│  Runs as a background service in the FastAPI process.             │
│  One bot instance per user (based on their bot token).            │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Bot Lifecycle Manager                                     │   │
│  │                                                            │   │
│  │  On user signup / settings update:                         │   │
│  │  ├── Validate bot token via Telegram API                   │   │
│  │  ├── Start bot instance for this user                      │   │
│  │  └── Register message handlers                             │   │
│  │                                                            │   │
│  │  On user disconnects:                                      │   │
│  │  ├── Stop bot instance                                     │   │
│  │  └── Clean up handlers                                     │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Per-User Bot Instance                                     │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  User A's Bot                                        │  │   │
│  │  │  ├── Token: bot123:ABC...                            │  │   │
│  │  │  ├── Listening to:                                   │  │   │
│  │  │  │   ├── "Tech Jobs India" (group)                   │  │   │
│  │  │  │   ├── "Remote Python Jobs" (channel)              │  │   │
│  │  │  │   └── "SF Startup Jobs" (group)                   │  │   │
│  │  │  └── Message handler: process_message()              │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  User B's Bot                                        │  │   │
│  │  │  ├── Token: bot456:DEF...                            │  │   │
│  │  │  ├── Listening to:                                   │  │   │
│  │  │  │   └── "Design Jobs NYC" (group)                   │  │   │
│  │  │  └── Message handler: process_message()              │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Message Processing                                        │   │
│  │                                                            │   │
│  │  Telegram message arrives:                                 │   │
│  │  "We're hiring! Senior Python Dev at Acme.                │   │
│  │   Apply here: https://greenhouse.io/jobs/12345"           │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  1. Extract URLs from message text                   │  │   │
│  │  │     → https://greenhouse.io/jobs/12345               │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │  ┌──────────────────────┴───────────────────────────────┐  │   │
│  │  │  2. Extract free context from surrounding text       │  │   │
│  │  │     (zero cost — regex and keyword lookup)           │  │   │
│  │  │                                                      │  │   │
│  │  │  ┌─────────────────┬────────────────────────────────┐│  │   │
│  │  │  │ Signal          │ How extracted                  ││  │   │
│  │  │  ├─────────────────┼────────────────────────────────┤│  │   │
│  │  │  │ Job title       │ "Senior Python Dev" = title    ││  │   │
│  │  │  │ Company name    │ "at Acme" or @handle           ││  │   │
│  │  │  │ Location hint   │ "NYC" / "Remote" / "Berlin"   ││  │   │
│  │  │  │ Salary range    │ "💰 $120-150k" = regex match   ││  │   │
│  │  │  └─────────────────┴────────────────────────────────┘│  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────┴───────────────────────────────┐  │   │
│  │  │  3. Detect platform from URL                         │  │   │
│  │  │     → greenhouse                                     │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────┴───────────────────────────────┐  │   │
│  │  │  4. Save job to PostgreSQL                           │  │   │
│  │  │     status: "discovered"                             │  │   │
│  │  │     source: "telegram"                               │  │   │
│  │  │     raw_message: (full text)                         │  │   │
│  │  │     user_id: (owner of this bot)                     │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────┴───────────────────────────────┐  │   │
│  │  │  5. Trigger JD Extraction (5-door cascade)           │  │   │
│  │  │     → Door 0: classify URL                           │  │   │
│  │  │     → Door 1: ATS API probe (GH/Lever) — 0 tokens   │  │   │
│  │  │     → Door 2: JSON-LD label — 0 tokens               │  │   │
│  │  │     → Door 3: text strip — 0 tokens                  │  │   │
│  │  │     → Door 4: LLM parse — ~1 call (if needed)        │  │   │
│  │  │     → Door 5: gap-fill — 0-1 calls (if needed)       │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────┴───────────────────────────────┐  │   │
│  │  │  6. Job stored with full extraction                  │  │   │
│  │  │     → Rubric Generator creates scoring rubric        │  │   │
│  │  │     → Scorer evaluates profile                       │  │   │
│  │  │     → Result: scored job, regardless of match        │  │   │
│  │  │                                                      │  │   │
│  │  │  RULE: Every job is extracted and stored.            │  │   │
│  │  │  Jobs not shown are left in jobs.status.             │  │   │
│  │  │  applications.skip_reason records fill blockers.     │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Isolation Model

```
User A's bot ──only sees──▶ User A's groups/channels
User B's bot ──only sees──▶ User B's groups/channels

No cross-user data leakage.
Each bot token is unique per user.
Each bot is added to groups by its owner only.
```
