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
    content: str  # LLM response text
    provider: str  # which provider answered (e.g., "gemini")
    model: str  # model used (e.g., "gemini-2.0-flash")
    prompt_tokens: int  # tokens in prompt
    completion_tokens: int  # tokens in response
    latency_ms: int  # round-trip time
```

## JSON-Mode Lane (Internal Superset — Optional, Default-Off)

Strict structured output is **opt-in**. Without the flags below, `route_llm_request` is
byte-identical to the contract above — no wire flag set, no schema injected into the prompt, no
parsing. Steps that need only plain text never touch this lane.

```python
def generate_structured(
    prompt: str,
    system_message: str,
    user_id: str,
    output_model: type,          # pydantic model to validate against
    provider_chain: list[str] | None = None,  # overrides user settings
    job_id: str | None = None,   # accepted for usage keying (optional)
    step: str | None = None,     # accepted for usage keying (optional)
    max_repairs: int = 1,        # bounded re-prompt to the same provider
) -> output_model
```

**Behavior:**

1. **Wire flags** — each adapter sets its provider-native JSON knob only when opted in:
   OpenAI-compatible → `response_format={"type":"json_object"}` (or `json_schema`); Gemini →
   `generationConfig.response_mime_type="application/json"`; Ollama → `format: "json"`.
2. **Prompt** — a schema/example block is appended ("respond with only valid JSON …") when opted
   in, satisfying providers that require the token "json" in the prompt.
3. **Tolerant parse** — `parse_llm_json(text)`: strip surrounding prose, extract the first fenced
   ```json block, unwrap single-key wrappers (`{"result": ...}` / `{"output": ...}`), balanced-brace
   repair on truncation; then **pydantic** validation against `output_model`.
4. **Failure semantics** — a 200 response that fails parse/validate counts as a normal **failed
   attempt**: `provider_usage` records `error_type` (`invalid_json` / `schema_mismatch`), audit
   `llm_provider_failed`, one optional bounded repair prompt to the same provider, else advance the
   chain. **The circuit breaker is never tripped by output-shape failures** — only HTTP
   429/5xx/timeout do.

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
| `name` | Canonical lowercase provider key (e.g., `gemini`, `openrouter`) — validated against the **provider registry** (`backend/app/llm/registry.py`, D19); the DB enforces lowercase only (migration 027) |
| `base_url` | API endpoint (e.g., "https://generativelanguage.googleapis.com") |
| `api_key` | API key **encrypted with AES-256-GCM at rest** (`nonce:ciphertext` in `api_key_encrypted`, 32-byte master key from `LLM_PROVIDER_MASTER_KEY`); decrypted **in-memory only** at call/test time; **never returned** in responses, never echoed/logged (D18, implemented in S4) |
| `model` | Model name (e.g., "gemini-2.0-flash") |
| `priority` | Order in chain (1 = first to try) |
| `is_active` | Whether provider is enabled |

> **Capability gate (post-027, D19):** `llm_providers.name` is not schema-restricted to a fixed
> provider list. Whether a name is callable is decided by the registry — an unregistered `name`
> is rejected at create (`VALIDATION_ERROR`) and treated as **unavailable** by the router.

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
  llm_router → llm_providers (INSERT with name, base_url, api_key stored AES-256-GCM-encrypted — D18)

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
