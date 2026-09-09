# LLM Router

Routes LLM requests across providers with automatic failover.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                         LLM ROUTER                                │
│                                                                   │
│  Any component in Core Engine makes an LLM call:                  │
│  ├── Extraction (per section)                                     │
│  ├── Scoring (evaluation)                                         │
│  ├── Optimization (rewrite)                                       │
│  ├── JD Extraction (parse)                                        │
│  └── Rubric Generation (generate)                                 │
│                                                                   │
│                           │                                       │
│                           ▼                                       │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │                     LLM ROUTER                             │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  1. Resolve User's Provider Chain                    │  │   │
│  │  │                                                      │  │   │
│  │  │  User settings: ["gemini", "ollama", "groq"]         │  │   │
│  │  │  (ordered by preference)                             │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  2. Check Circuit Breaker State                      │  │   │
│  │  │                                                      │  │   │
│  │  │  For each provider in chain:                         │  │   │
│  │  │  ├── CLOSED (healthy) → try it                       │  │   │
│  │  │  ├── OPEN (failed) → skip, try next                  │  │   │
│  │  │  └── HALF_OPEN (cooling down) → try one request      │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │                         ▼                                  │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  3. Make Request                                     │  │   │
│  │  │                                                      │  │   │
│  │  │  Using OpenAICompatibleProvider from hiring-agent:   │  │   │
│  │  │  ├── Set base_url from provider config               │  │   │
│  │  │  ├── Set api_key (decrypted from DB)                 │  │   │
│  │  │  ├── Set model parameters (temperature, top_p)       │  │   │
│  │  │  └── Call provider.chat()                            │  │   │
│  │  └──────────────────────┬───────────────────────────────┘  │   │
│  │                         │                                  │   │
│  │              ┌──────────┴──────────┐                       │   │
│  │              │                     │                       │   │
│  │              ▼ SUCCESS             ▼ FAILURE               │   │
│  │  ┌──────────────────────┐  ┌──────────────────────┐       │   │
│  │  │ Return response      │  │ Record failure:      │       │   │
│  │  │ Reset circuit breaker│  │ ├── 429 → open circuit│       │   │
│  │  │ Log token usage      │  │ ├── 500 → retry next │       │   │
│  │  └──────────────────────┘  │ └── timeout → skip   │       │   │
│  │                            └──────────┬───────────┘       │   │
│  │                                       │                   │   │
│  │                                       ▼                   │   │
│  │                            ┌──────────────────────┐       │   │
│  │                            │ Try next provider    │       │   │
│  │                            │ in chain             │       │   │
│  │                            └──────────┬───────────┘       │   │
│  │                                       │                   │   │
│  │                                       ▼                   │   │
│  │                            ┌──────────────────────┐       │   │
│  │                            │ All failed?          │       │   │
│  │                            │                      │       │   │
│  │                            │ → Save checkpoint    │       │   │
│  │                            │ → Notify user        │       │   │
│  │                            │ → "Switch keys or    │       │   │
│  │                            │    wait for reset"   │       │   │
│  │                            └──────────────────────┘       │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Provider Chain (Per User)

```
User A configures:  [Gemini, Ollama, Groq]
User B configures:  [Ollama, Gemini]
User C configures:  [Groq, OpenRouter, Gemini]

Each user has their own ordered chain.
Router tries providers in user's preferred order.

Shared circuit breaker states:
├── gemini:   CLOSED (healthy)
├── ollama:   CLOSED (healthy)
├── groq:     OPEN (rate limited, cooldown 60s)
└── openrouter: HALF_OPEN (testing after failure)
```

---

## Rate Limit Handling

```
Provider        Rate Limit          Response
──────────────────────────────────────────────────
Gemini Free     15 RPM              429 + Retry-After header
Groq Free       30 RPM              429 + Retry-After header
OpenRouter Free 1-2 RPM             429
Ollama Local    Unlimited           503 if model loading

Router actions on 429:
1. Parse Retry-After header
2. Wait (with jitter: ±20%)
3. Mark circuit OPEN for cooldown period
4. Try next provider immediately
```
