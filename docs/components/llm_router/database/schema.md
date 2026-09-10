# LLM Router — Schema

Tables owned by the llm_router component.

> **Canonical source:** `docs/database/schema.md` — migration 005 (llm_providers), 014 (provider_usage), 016 (rate_limit_state), 027 (provider-name CHECK lifted).
> If any column differs here vs canonical, canonical wins.
>
> **Post-027 (S4 · D19):** `llm_providers.name` is **not** restricted to the original 4 providers.
> The database enforces lowercase only (`CHECK (name = lower(name))`); the **provider registry**
> (`backend/app/llm/registry.py`) is the capability gate — `name` must be a registered adapter
> key, and unregistered names are treated as unavailable by the router.

---

## llm_providers

```sql
CREATE TABLE llm_providers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (name = lower(name)),
    base_url TEXT NOT NULL,
    api_key_encrypted TEXT,
    model TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    priority INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_llm_providers_user_id ON llm_providers(user_id);
CREATE INDEX idx_llm_providers_priority ON llm_providers(user_id, priority);
```

---

## provider_usage

```sql
CREATE TABLE provider_usage (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider_id UUID NOT NULL REFERENCES llm_providers(id) ON DELETE CASCADE,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL,
    success BOOLEAN NOT NULL,
    error_type TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_provider_usage_job_id ON provider_usage(job_id);
CREATE INDEX idx_provider_usage_provider_id ON provider_usage(provider_id);
CREATE INDEX idx_provider_usage_user_id ON provider_usage(user_id);
```

---

## rate_limit_state

```sql
CREATE TABLE rate_limit_state (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider_name TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state TEXT NOT NULL DEFAULT 'CLOSED' CHECK (state IN ('OPEN', 'CLOSED', 'HALF_OPEN')),
    failure_count INTEGER NOT NULL DEFAULT 0,
    last_failure_at TIMESTAMPTZ,
    cooldown_expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(provider_name, user_id)
);

CREATE INDEX idx_rate_limit_provider_user ON rate_limit_state(provider_name, user_id);
```
