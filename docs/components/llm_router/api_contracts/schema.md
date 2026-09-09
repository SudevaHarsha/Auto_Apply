# LLM Router — API Contract

> **Owns:** None (no HTTP endpoints — all internal function calls)
> **Consumed by:** Core Engine components via direct function imports
> **Canonical source:** `docs/api_contracts/schema.md` — llm_router is called internally, not via HTTP

---

## Internal Functions (Not HTTP)

The LLM Router exposes a single routing function called by Core Engine components:

```python
def route_llm_request(
    prompt: str,
    system_message: str,
    user_id: str,
    provider_chain: list[str] | None = None  # overrides user settings
) -> LLMResponse
```

**Returns:**
```python
@dataclass
class LLMResponse:
    content: str           # LLM response text
    provider: str          # which provider answered (e.g., "gemini")
    model: str             # model used (e.g., "gemini-2.0-flash")
    prompt_tokens: int     # tokens in prompt
    completion_tokens: int # tokens in response
    latency_ms: int        # round-trip time
```

---

## Provider Chain Resolution

```
1. Read user's provider chain from settings (llm_chain key)
   Default: ["gemini", "ollama", "groq", "openrouter"]

2. For each provider in chain:
   a. Check circuit breaker state (rate_limit_state table)
   b. CLOSED (healthy) → try it
   c. OPEN (failed) → skip, try next
   d. HALF_OPEN (cooling down) → try one request

3. Make request via OpenAICompatibleProvider (from hiring-agent-main)

4. On success:
   - Reset circuit breaker → CLOSED
   - Log token usage to provider_usage
   - Return response

5. On failure:
   - 429 → open circuit, parse Retry-After, try next
   - 500 → try next provider
   - timeout → skip, try next

6. All failed:
   - Save checkpoint
   - Notify user
   - "Switch keys or wait for reset"
```

---

## Circuit Breaker States

| State | Behavior |
|-------|----------|
| CLOSED | Healthy, requests flow through |
| OPEN | Failed, requests blocked for cooldown period |
| HALF_OPEN | Testing after cooldown, one request allowed |

---

## Rate Limit Handling

| Provider | Free Tier Limit | Response on 429 |
|----------|----------------|-----------------|
| Gemini Free | 15 RPM | Parse Retry-After, wait with jitter (±20%) |
| Groq Free | 30 RPM | Parse Retry-After, wait with jitter (±20%) |
| OpenRouter Free | 1-2 RPM | Mark circuit OPEN |
| Ollama Local | Unlimited | 503 if model loading |

---

## Provider Configuration

Each provider is configured per-user in `llm_providers` table:

| Field | Description |
|-------|-------------|
| `name` | Display name (e.g., "Gemini Flash") |
| `base_url` | API endpoint (e.g., "https://generativelanguage.googleapis.com") |
| `api_key` | Encrypted API key (AES-256) |
| `model` | Model name (e.g., "gemini-2.0-flash") |
| `priority` | Order in chain (1 = first to try) |
| `is_active` | Whether provider is enabled |

---

## Usage Tracking

Every successful LLM call logs to `provider_usage`:

| Field | Description |
|-------|-------------|
| `provider_id` | FK to llm_providers |
| `user_id` | FK to users |
| `job_id` | FK to jobs (if applicable) |
| `prompt_tokens` | Tokens in prompt |
| `completion_tokens` | Tokens in response |
| `latency_ms` | Round-trip time |
| `created_at` | Timestamp |

---

## Data Flow (Internal)

```
CONFIGURE PROVIDER:
  llm_router → llm_providers (INSERT with name, base_url, encrypted key)

LLM REQUEST:
  llm_router → provider_usage (INSERT prompt_tokens, completion_tokens, latency_ms)

PROVIDER FAILS:
  llm_router → rate_limit_state (INSERT or UPDATE state=CLOSED → OPEN)

PROVIDER RECOVERS:
  llm_router → rate_limit_state (UPDATE state=HALF_OPEN → CLOSED)

CIRCUIT OPENS:
  llm_router → rate_limit_state (UPDATE failure_count, cooldown_expires_at)

ALL PROVIDERS DOWN:
  llm_router → rate_limit_state (all circuits OPEN)
```

---

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Single provider 429 | Open circuit, try next provider |
| Single provider 500 | Try next provider |
| Single provider timeout | Skip, try next |
| All providers exhausted | Save checkpoint, notify user |
| Ollama not running | Skip (treat as unavailable) |
| Invalid API key | Mark provider as failed, try next |

---

## Audit Actions

| Internal Event | Audit Action | Resource Type |
|----------------|-------------|---------------|
| Provider added | `llm_provider_added` | llm_provider |
| Provider removed | `llm_provider_removed` | llm_provider |
| Provider call failed | `llm_provider_failed` | llm_provider |
| All providers exhausted | `all_providers_exhausted` | system |
