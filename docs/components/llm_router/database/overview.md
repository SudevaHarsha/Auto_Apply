# LLM Router — Database Scope

Owns provider configuration, usage tracking, and circuit breaker state.

---

## Tables Owned

```
TABLE              PURPOSE                              WRITES
────────────────────────────────────────────────────────────
llm_providers      User's LLM provider config            CREATE, UPDATE, DELETE
provider_usage     Per-request LLM usage tracking         INSERT
rate_limit_state   Circuit breaker state (persisted)      CREATE, UPDATE
```

---

## Tables Read

```
TABLE             READ BY              WHY
───────────────────────────────────────────────────
audit_logs        llm_router           reads provider failure history
```

---

## Tables Written (INSERT only, no ownership)

```
TABLE             WRITER               WHY
────────────────────────────────────────────────────
audit_logs        llm_router           logs provider failures, circuit events (INSERT)
```

---

## Data Flow

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

## Relationships

```
users (1) ──────< (N) llm_providers
users (1) ──────< (N) rate_limit_state

llm_providers (1) ──< (N) provider_usage
jobs (1) ──────────< (N) provider_usage
```
