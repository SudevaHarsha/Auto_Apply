# Database Schema — SQL Migrations

Full SQL schema for AutoApply. Run migrations in order.

---

## Migration 001: Create Users Table

```sql
-- File: migrations/001_create_users.sql

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_users_email ON users(email);
```

---

## Migration 002: Create Profiles Table

```sql
-- File: migrations/002_create_profiles.sql

CREATE TABLE profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    original_pdf_url TEXT NOT NULL,
    json_resume JSONB NOT NULL,
    last_scored_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_profiles_user_id ON profiles(user_id);
```

---

## Migration 003: Create Jobs Table

```sql
-- File: migrations/003_create_jobs.sql

CREATE TABLE jobs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    company TEXT NOT NULL,
    url TEXT NOT NULL,
    platform TEXT NOT NULL CHECK (platform IN ('greenhouse', 'lever', 'linkedin', 'indeed', 'workday', 'generic')),
    source TEXT NOT NULL CHECK (source IN ('telegram', 'discord', 'manual')),
    status TEXT NOT NULL DEFAULT 'discovered' CHECK (status IN ('discovered', 'scored', 'approved', 'applying', 'applied', 'rejected', 'skipped', 'failed')),
    score INTEGER CHECK (score >= 0 AND score <= 100),
    raw_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, url)
);

CREATE INDEX idx_jobs_user_id ON jobs(user_id);
CREATE INDEX idx_jobs_status ON jobs(user_id, status);
```

---

## Migration 004: Create Applications Table

```sql
-- File: migrations/004_create_applications.sql

CREATE TABLE applications (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    optimized_resume JSONB NOT NULL,
    cover_letter TEXT,
    pdf_url TEXT NOT NULL,
    field_mappings JSONB NOT NULL,
    required_fields JSONB DEFAULT '[]'::jsonb,
    fill_details JSONB DEFAULT '[]'::jsonb,
    status TEXT NOT NULL DEFAULT 'created' CHECK (status IN ('created', 'filling', 'filled', 'submitted', 'skipped', 'failed')),
    skip_reason TEXT,
    screenshot_url TEXT,
    filled_at TIMESTAMPTZ,
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_applications_user_id ON applications(user_id);
CREATE INDEX idx_applications_job_id ON applications(job_id);
CREATE INDEX idx_applications_status ON applications(user_id, status);
```

---

## Migration 005: Create LLM Providers Table

```sql
-- File: migrations/005_create_llm_providers.sql

CREATE TABLE llm_providers (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (name IN ('gemini', 'ollama', 'groq', 'openrouter')),
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

## Migration 006: Create Checkpoints Table

```sql
-- File: migrations/006_create_checkpoints.sql

CREATE TABLE checkpoints (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    pipeline_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    step TEXT NOT NULL CHECK (step IN ('jd_extraction', 'rubric_generation', 'scoring', 'optimization', 'package_generation')),
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_checkpoints_user_id ON checkpoints(user_id);
CREATE INDEX idx_checkpoints_job_id ON checkpoints(job_id);
```

---

## Migration 007: Enable RLS + Create Policies

```sql
-- File: migrations/007_enable_rls.sql

-- Enable RLS on all tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_messages ENABLE ROW LEVEL SECURITY;

-- Create policies using SET LOCAL app.user_id pattern
CREATE POLICY user_isolation ON users
    USING (id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON profiles
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON jobs
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON applications
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON llm_providers
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON checkpoints
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON discord_connections
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON discord_messages
    USING (user_id = current_setting('app.user_id')::uuid);
```

---

## Migration 008: Updated At Trigger

```sql
-- File: migrations/008_updated_at_trigger.sql

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ language 'plpgsql';

CREATE TRIGGER update_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_jobs_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_llm_providers_updated_at
    BEFORE UPDATE ON llm_providers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_checkpoints_updated_at
    BEFORE UPDATE ON checkpoints
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

## Migration 009: Create Evidence Table

```sql
-- File: migrations/009_create_evidence.sql

CREATE TABLE evidence (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    application_id UUID REFERENCES applications(id) ON DELETE CASCADE,  -- NULL for profile_diff, jd_raw, message_raw
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    type TEXT NOT NULL CHECK (type IN ('screenshot', 'pdf', 'dom_snapshot', 'profile_diff', 'jd_raw', 'message_raw')),
    file_url TEXT NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_evidence_application_id ON evidence(application_id);
CREATE INDEX idx_evidence_user_id ON evidence(user_id);
```

---

## Migration 010: Create Telegram Connections Table

```sql
-- File: migrations/010_create_telegram_connections.sql

CREATE TABLE telegram_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bot_token TEXT NOT NULL,  -- encrypted with AES-256 via application layer
    bot_username TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'disconnected' CHECK (status IN ('connected', 'disconnected', 'error')),
    groups JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_telegram_connections_user_id ON telegram_connections(user_id);
```

---

## Migration 011: Create API Keys Table

```sql
-- File: migrations/011_create_api_keys.sql

CREATE TABLE api_keys (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key_hash TEXT NOT NULL,
    name TEXT NOT NULL,
    prefix TEXT NOT NULL,
    last_used_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_api_keys_user_id ON api_keys(user_id);
CREATE INDEX idx_api_keys_prefix ON api_keys(prefix);
```

---

## Migration 012: Create Audit Logs Table

```sql
-- File: migrations/012_create_audit_logs.sql

CREATE TABLE audit_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id UUID,
    details JSONB DEFAULT '{}'::jsonb,
    ip_address INET,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX idx_audit_logs_action ON audit_logs(user_id, action);
```

---

## Migration 013: Create Settings Table

```sql
-- File: migrations/013_create_settings.sql

CREATE TABLE settings (
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    key TEXT NOT NULL,
    value JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, key)
);
```

---

## Migration 014: Create Provider Usage Table

```sql
-- File: migrations/014_create_provider_usage.sql

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

## Migration 015: Create Pipeline Runs Table

```sql
-- File: migrations/015_create_pipeline_runs.sql

CREATE TABLE pipeline_runs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    job_id UUID NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'running' CHECK (status IN ('running', 'completed', 'failed', 'paused')),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    steps_run TEXT[] NOT NULL DEFAULT '{}',
    total_time_ms INTEGER,
    error_message TEXT,
    trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'auto')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_pipeline_runs_job_id ON pipeline_runs(job_id);
CREATE INDEX idx_pipeline_runs_user_id ON pipeline_runs(user_id);
```

---

## Migration 016: Create Rate Limit State Table

```sql
-- File: migrations/016_create_rate_limit_state.sql

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

---

## Migration 017: Create Telegram Messages Table

```sql
-- File: migrations/017_create_telegram_messages.sql

CREATE TABLE telegram_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    chat_title TEXT,
    message_id BIGINT NOT NULL,
    text TEXT,
    urls_found TEXT[] NOT NULL DEFAULT '{}',
    job_created BOOLEAN NOT NULL DEFAULT FALSE,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, chat_id, message_id)
);

CREATE INDEX idx_telegram_messages_user_id ON telegram_messages(user_id);
CREATE INDEX idx_telegram_messages_chat ON telegram_messages(user_id, chat_id);
```

---

## Migration 018: Create Error Logs Table

```sql
-- File: migrations/018_create_error_logs.sql

CREATE TABLE error_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    component TEXT NOT NULL,
    error_type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO')),
    message TEXT NOT NULL,
    context JSONB,
    provider TEXT,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_action TEXT,
    stack_trace TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_error_logs_user_id ON error_logs(user_id);
CREATE INDEX idx_error_logs_component ON error_logs(component);
CREATE INDEX idx_error_logs_severity ON error_logs(severity);
CREATE INDEX idx_error_logs_job_id ON error_logs(job_id);
CREATE INDEX idx_error_logs_created_at ON error_logs(created_at);
```

---

## Migration 019: Enable RLS on New Tables

```sql
-- File: migrations/019_enable_rls_new_tables.sql

ALTER TABLE evidence ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE api_keys ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE error_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE provider_usage ENABLE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE rate_limit_state ENABLE ROW LEVEL SECURITY;
ALTER TABLE telegram_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_isolation ON evidence
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON telegram_connections
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON api_keys
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON audit_logs
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON error_logs
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON settings
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON provider_usage
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON pipeline_runs
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON rate_limit_state
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON telegram_messages
    USING (user_id = current_setting('app.user_id')::uuid);
```

---

## Migration 020: Immutability Triggers + Anonymization

```sql
-- File: migrations/020_immutable_triggers.sql

-- audit_logs: prevent UPDATE and DELETE (except anonymization)
CREATE OR REPLACE FUNCTION prevent_audit_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    -- Allow anonymization: setting user_id to anonymous UUID
    IF OLD.user_id = NEW.user_id THEN
        RAISE EXCEPTION 'audit_logs are immutable — UPDATE and DELETE are not allowed';
    END IF;
    -- Allow anonymization: setting user_id to anonymous UUID
    IF NEW.user_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'audit_logs are immutable — UPDATE and DELETE are not allowed';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_logs_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_audit_log_modification();

-- error_logs: prevent UPDATE and DELETE (except anonymization)
CREATE OR REPLACE FUNCTION prevent_error_log_modification()
RETURNS TRIGGER AS $$
BEGIN
    -- Allow anonymization: setting user_id to anonymous UUID
    IF OLD.user_id = NEW.user_id THEN
        RAISE EXCEPTION 'error_logs are immutable — UPDATE and DELETE are not allowed';
    END IF;
    -- Allow anonymization: setting user_id to anonymous UUID
    IF NEW.user_id = '00000000-0000-0000-0000-000000000000'::uuid THEN
        RETURN NEW;
    END IF;
    RAISE EXCEPTION 'error_logs are immutable — UPDATE and DELETE are not allowed';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER error_logs_immutable
    BEFORE UPDATE OR DELETE ON error_logs
    FOR EACH ROW
    EXECUTE FUNCTION prevent_error_log_modification();

-- Anonymization function: strips PII from audit_logs
CREATE OR REPLACE FUNCTION anonymize_audit_logs(p_user_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE audit_logs
    SET
        user_id = '00000000-0000-0000-0000-000000000000'::uuid,
        details = details - 'name' - 'email' - 'ip_address',
        ip_address = NULL
    WHERE user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

-- Anonymization function: strips PII from error_logs
CREATE OR REPLACE FUNCTION anonymize_error_logs(p_user_id UUID)
RETURNS VOID AS $$
BEGIN
    UPDATE error_logs
    SET
        user_id = '00000000-0000-0000-0000-000000000000'::uuid,
        message = REGEXP_REPLACE(message, '\S+@\S+', '[REDACTED]', 'g'),
        stack_trace = NULL
    WHERE user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;

-- Account deletion: anonymize logs, then cascade delete everything else
CREATE OR REPLACE FUNCTION delete_user_account(p_user_id UUID)
RETURNS VOID AS $$
BEGIN
    -- Step 1: Anonymize audit logs (keep for legal, remove PII)
    PERFORM anonymize_audit_logs(p_user_id);

    -- Step 2: Anonymize error logs (keep for legal, remove PII)
    PERFORM anonymize_error_logs(p_user_id);

    -- Step 3: Cascade delete all user data (logs stay anonymized)
    DELETE FROM users WHERE id = p_user_id;
END;
$$ LANGUAGE plpgsql;
```

---

## Anonymization Reference

```
ANONYMIZE BEFORE DELETE:

audit_logs:
  ├── user_id → '00000000-0000-0000-0000-000000000000'
  ├── details → strip 'name', 'email', 'ip_address' keys
  └── ip_address → NULL

error_logs:
  ├── user_id → '00000000-0000-0000-0000-000000000000'
  ├── message → regex replace emails with [REDACTED]
  └── stack_trace → NULL

DELETE (cascade):
  ├── users
  ├── profiles
  ├── jobs
  ├── applications
  ├── evidence
  ├── llm_providers
  ├── telegram_connections
  ├── discord_connections
  ├── checkpoints
  ├── api_keys
  ├── settings
  ├── provider_usage
  ├── pipeline_runs
  ├── rate_limit_state
  ├── telegram_messages
  ├── discord_messages
  └── (audit_logs, error_logs stay anonymized)

ANONYMOUS UUID: 00000000-0000-0000-0000-000000000000
  - Not a real user
  - Query: WHERE user_id = '00000000-...'
  - Shows "Anonymous (deleted user)" in dashboard
```

---

## Migration 021: Updated At Triggers for New Tables

```sql
-- File: migrations/021_updated_at_triggers_new.sql

CREATE TRIGGER update_settings_updated_at
    BEFORE UPDATE ON settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_rate_limit_state_updated_at
    BEFORE UPDATE ON rate_limit_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

## Migration 022: Discord Integration

```sql
-- File: migrations/022_create_discord_tables.sql

CREATE TABLE discord_connections (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    bot_token TEXT NOT NULL,  -- encrypted with AES-256 via application layer
    bot_username TEXT,
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'error')),
    chat_mode TEXT DEFAULT 'bot' CHECK (chat_mode IN ('bot', 'agent')),
    notifications_enabled BOOLEAN DEFAULT TRUE,
    notification_events TEXT[] DEFAULT '{job_discovered,pipeline_completed,pipeline_failed,application_submitted}',
    servers JSONB DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_discord_connections_uid ON discord_connections(user_id);

CREATE TABLE discord_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    server_id BIGINT,  -- NULL for DMs
    server_name TEXT,
    channel_id BIGINT NOT NULL,
    channel_name TEXT,  -- "DM" for direct messages
    message_id BIGINT NOT NULL,
    author_id BIGINT NOT NULL,
    is_dm BOOLEAN DEFAULT FALSE,
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    text TEXT,
    urls_found TEXT[] DEFAULT '{}',
    job_created BOOLEAN DEFAULT FALSE,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, channel_id, message_id)
);

CREATE INDEX idx_discord_messages_user_id ON discord_messages(user_id);
CREATE INDEX idx_discord_messages_server ON discord_messages(user_id, server_id);
CREATE INDEX idx_discord_messages_dm ON discord_messages(user_id, is_dm) WHERE is_dm = TRUE;

-- RLS
ALTER TABLE discord_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY discord_connections_isolated ON discord_connections
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY discord_messages_isolated ON discord_messages
    USING (user_id = current_setting('app.user_id')::uuid);
```

---

## Entity Relationship Diagram

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│    users     │     │   profiles   │     │     jobs     │
├──────────────┤     ├──────────────┤     ├──────────────┤
│ id (PK)      │────<│ user_id (FK) │     │ id (PK)      │
│ email        │     │ id (PK)      │     │ user_id (FK) │
│ password_hash│     │ original_pdf │     │ title        │
│ name         │     │ json_resume  │     │ company      │
│ created_at   │     │ last_scored  │     │ url          │
│ updated_at   │     │ created_at   │     │ platform     │
└──────┬───────┘     └──────────────┘     │ source       │
       │                                   │ status       │
       │                                   │ score        │
       │                                   │ raw_message  │
       │                                   │ created_at   │
       │                                   │ updated_at   │
       │                                   └──────┬───────┘
       │                                          │
       │     ┌──────────────┐     ┌───────────────┘
       │     │ applications │     │
       │     ├──────────────┤     │
       └────<│ user_id (FK) │     │
             │ id (PK)      │     │
             │ job_id (FK)  │─────┘
             │ profile_id(FK│
             │ optimized_res│
             │ cover_letter │
             │ pdf_url      │
             │ field_mappings
             │ status       │
             │ screenshot_url
             │ filled_at    │
             │ submitted_at │
             │ created_at   │
             └──────┬───────┘
                    │
                    │ 1:N
                    ▼
             ┌──────────────┐
             │  evidence    │
             ├──────────────┤
             │ id (PK)      │
             │ application_ │
             │   id (FK)    │
             │ user_id (FK) │
             │ type         │
             │ file_url     │
             │ metadata     │
             │ created_at   │
             └──────────────┘

┌──────────────┐  ┌──────────────┐  ┌──────────────┐
│llm_providers │  │ checkpoints  │  │  api_keys    │
├──────────────┤  ├──────────────┤  ├──────────────┤
│ id (PK)      │  │ id (PK)      │  │ id (PK)      │
│ user_id (FK) │  │ user_id (FK) │  │ user_id (FK) │
│ name         │  │ job_id (FK)  │  │ key_hash     │
│ base_url     │  │ pipeline_state│  │ name         │
│ api_key_enc  │  │ step         │  │ prefix       │
│ model        │  │ error_message│  │ last_used_at │
│ is_active    │  │ created_at   │  │ expires_at   │
│ priority     │  │ updated_at   │  │ created_at   │
│ created_at   │  └──────────────┘  └──────────────┘
│ updated_at   │
└──────┬───────┘
       │ 1:N
       ▼
┌───────────────┐     ┌──────────────┐     ┌──────────────┐
│provider_usage │     │pipeline_runs │     │ rate_limit_  │
├───────────────┤     ├──────────────┤     │   state      │
│ id (PK)       │     │ id (PK)      │     ├──────────────┤
│ user_id (FK)  │     │ user_id (FK) │     │ id (PK)      │
│ provider_id FK│     │ job_id (FK)  │     │ provider_name│
│ job_id (FK)   │     │ status       │     │ user_id (FK) │
│ prompt_tokens │     │ started_at   │     │ state        │
│ completion_   │     │ completed_at │     │ failure_count│
│   tokens      │     │ steps_run [] │     │ last_failure │
│ latency_ms    │     │ total_time_ms│     │ cooldown_exp │
│ success       │     │ error_message│     │ created_at   │
│ error_type    │     │ trigger      │     │ updated_at   │
│ created_at    │     │ created_at   │     └──────────────┘
└───────────────┘     └──────────────┘

┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
│ audit_logs   │  │ error_logs   │  │  settings        │
├──────────────┤  ├──────────────┤  ├──────────────────┤
│ id (PK)      │  │ id (PK)      │  │ user_id (FK) +   │
│ user_id (FK) │  │ user_id (FK) │  │ key (PK)         │
│ action       │  │ component    │  │ value            │
│ resource_type│  │ error_type   │  │ created_at       │
│ resource_id  │  │ severity     │  │ updated_at       │
│ details      │  │ message      │  └──────────────────┘
│ ip_address   │  │ context      │
│ created_at   │  │ provider     │
└──────────────┘  │ job_id (FK)  │
                  │ retry_count  │
                  │ next_action  │
                  │ stack_trace  │
                  │ created_at   │
                  └──────────────┘
┌──────────────────┐  ┌──────────────────┐
│telegram_connections│  │discord_connections│
├──────────────────┤  ├──────────────────┤
│ id (PK)          │  │ id (PK)          │
│ user_id (FK)     │  │ user_id (FK)     │
│ bot_token        │  │ bot_token        │
│ bot_username     │  │ bot_username     │
│ status           │  │ status           │
│ groups []        │  │ chat_mode        │
│ created_at       │  │ notifications    │
└──────────────────┘  │ events []        │
                      │ servers []       │
                      │ created_at       │
                      │ updated_at       │
                      └──────────────────┘

┌──────────────────┐  ┌──────────────────┐
│telegram_messages │  │ discord_messages │
├──────────────────┤  ├──────────────────┤
│ id (PK)          │  │ id (PK)          │
│ user_id (FK)     │  │ user_id (FK)     │
│ chat_id          │  │ server_id        │
│ chat_title       │  │ server_name      │
│ message_id       │  │ channel_id       │
│ text             │  │ channel_name     │
│ urls_found []    │  │ message_id       │
│ job_created      │  │ author_id        │
│ job_id (FK)      │  │ is_dm            │
│ created_at       │  │ direction        │
└──────────────────┘  │ text             │
                      │ urls_found []    │
                      │ job_created      │
                      │ job_id (FK)      │
                      │ created_at       │
                      └──────────────────┘
```

---

## Migration 023: App User Role + FORCE ROW LEVEL SECURITY

```sql
-- File: migrations/023_app_user_role.sql

-- 1. Create dedicated app_user role (non-superuser, non-owner)
CREATE ROLE app_user LOGIN PASSWORD 'changeme_in_production';

-- Grant usage on public schema
GRANT USAGE ON SCHEMA public TO app_user;

-- Grant table permissions
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_user;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_user;

-- 2. Apply FORCE ROW LEVEL SECURITY to all 19 tables
ALTER TABLE users FORCE ROW LEVEL SECURITY;
ALTER TABLE profiles FORCE ROW LEVEL SECURITY;
ALTER TABLE jobs FORCE ROW LEVEL SECURITY;
ALTER TABLE applications FORCE ROW LEVEL SECURITY;
ALTER TABLE evidence FORCE ROW LEVEL SECURITY;
ALTER TABLE llm_providers FORCE ROW LEVEL SECURITY;
ALTER TABLE telegram_connections FORCE ROW LEVEL SECURITY;
ALTER TABLE discord_connections FORCE ROW LEVEL SECURITY;
ALTER TABLE discord_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE checkpoints FORCE ROW LEVEL SECURITY;
ALTER TABLE api_keys FORCE ROW LEVEL SECURITY;
ALTER TABLE audit_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE settings FORCE ROW LEVEL SECURITY;
ALTER TABLE provider_usage FORCE ROW LEVEL SECURITY;
ALTER TABLE pipeline_runs FORCE ROW LEVEL SECURITY;
ALTER TABLE rate_limit_state FORCE ROW LEVEL SECURITY;
ALTER TABLE telegram_messages FORCE ROW LEVEL SECURITY;
ALTER TABLE error_logs FORCE ROW LEVEL SECURITY;
ALTER TABLE user_profiles FORCE ROW LEVEL SECURITY;

-- 3. Connection string for FastAPI (use in .env)
-- DATABASE_URL=postgresql://app_user:<password>@localhost:5432/autoapply
-- (NOT postgres://... which would bypass RLS)
```

---

## Migration 024: User Profiles (Supplemental Personal Info)

```sql
-- File: migrations/024_create_user_profiles.sql

CREATE TABLE user_profiles (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    phone TEXT,
    linkedin_url TEXT,
    github_url TEXT,
    website_url TEXT,
    address TEXT,
    city TEXT,
    state TEXT,
    country TEXT,
    postal_code TEXT,
    date_of_birth DATE,
    gender TEXT,
    ethnicity TEXT,
    veteran_status TEXT,
    disability_status TEXT,
    work_authorization TEXT,
    custom_fields JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id)
);

CREATE INDEX idx_user_profiles_user_id ON user_profiles(user_id);
```

### Purpose

Stores supplemental personal information that resumes rarely contain but job application forms commonly require. Used as fallback when `profiles.json_resume` is missing fields.

### Fallback Chain (Field Mapping)

```
Step 1: Extract from optimized_resume (JSONResume)
  name      → optimized_resume.basics.name
  email     → optimized_resume.basics.email
  phone     → optimized_resume.basics.phone
  linkedin  → optimized_resume.basics.profiles[platform=linkedin].url
  github    → optimized_resume.basics.profiles[platform=github].url
  website   → optimized_resume.basics.url

Step 2: Fallback to user_profiles (if null after Step 1)
  phone     → user_profiles.phone
  linkedin  → user_profiles.linkedin_url
  github    → user_profiles.github_url
  website   → user_profiles.website_url
  address   → user_profiles.address
  city      → user_profiles.city
  state     → user_profiles.state
  country   → user_profiles.country
  postal    → user_profiles.postal_code
  dob       → user_profiles.date_of_birth

Step 3: Check required fields per platform
  greenhouse: name, email, phone (required), resume (required)
  lever:      name, email (required), resume (required)
  linkedin:   name, email (required), resume (required)
  indeed:     name, email (required), resume (required)
  generic:    name, email (required), resume (required)

Step 4: If any required field is still null → add to required_fields[]
```

### Why FORCE ROW LEVEL SECURITY?

Regular RLS is bypassed by table owners (typically the `postgres` superuser). FORCE RLS ensures RLS applies to **everyone**, including the role that created the table. This is critical for the `app_user` pattern:

```
                    ┌─────────────────────────────────┐
                    │         PostgreSQL               │
                    │                                  │
  FastAPI ──────────│──▶ app_user (table owner)        │
  (DATABASE_URL)    │      │                           │
                    │      ├─▶ Regular RLS: BYPASSED   │
                    │      └─▶ FORCE RLS: ENFORCED     │
                    │                                  │
                    │  SET LOCAL app.user_id = UUID;   │
                    │  -- Now RLS filters by this user │
                    └─────────────────────────────────┘
```

### Transaction Pattern

Every FastAPI request must set the user context:

```python
async def get_db():
    async with async_session() as session:
        # Set the user_id for RLS enforcement
        await session.execute("SET LOCAL app.user_id = :user_id", {"user_id": current_user.id})
        yield session
```

---

## Migration 025: Job Snapshots + Freshness FSM

```sql
-- File: migrations/025_job_snapshots_freshness.sql

-- 1. Add freshness state to jobs (user-scoped, RLS protects it)
ALTER TABLE jobs
    ADD COLUMN freshness_state TEXT NOT NULL DEFAULT 'fresh'
        CHECK (freshness_state IN ('fresh', 'stale', 'expired')),
    ADD COLUMN content_hash TEXT,
    ADD COLUMN current_snapshot_id UUID,
    ADD COLUMN last_fetched_at TIMESTAMPTZ;

CREATE INDEX idx_jobs_freshness ON jobs(user_id, freshness_state);

-- 2. Shared job snapshots table (PUBLIC job data — NO user_id, RLS-exempt)
--    Stores immutable extraction results keyed by content fingerprint.
--    One extraction serves all users who see the same posting.
CREATE TABLE job_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    content_hash TEXT NOT NULL UNIQUE,
    payload JSONB NOT NULL,          -- full structured JD output (Door 1-5 result)
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Bind applications/rubrics to the snapshot version they were scored against
ALTER TABLE applications
    ADD COLUMN snapshot_id UUID REFERENCES job_snapshots(id) ON DELETE SET NULL;

ALTER TABLE jobs
    ADD CONSTRAINT fk_jobs_snapshot
        FOREIGN KEY (current_snapshot_id) REFERENCES job_snapshots(id) ON DELETE SET NULL;

-- 4. Freshness transition function (triggered on fetch / age)
CREATE OR REPLACE FUNCTION apply_freshness_fsm() RETURNS trigger AS $$
BEGIN
    IF NEW.freshness_state = 'fresh' AND OLD.freshness_state <> 'fresh' THEN
        NEW.freshness_state = 'fresh';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;
```

### Purpose

Immutably records **what we extracted, when**, so "what did we score against?" is forever answerable, and freshness checks compare content hashes instead of guessing.

### Freshness FSM (stake-tiered budgets)

| Tier | Budget | Meaning | Transition |
|---|---|---|---|
| Search-tier | 72h | listing considered current for discovery/ranking | `fresh → stale` after 72h |
| Package-tier | 6h | re-check before the extension opens the form | `stale → expired` if confirm fails |

`content_hash` is computed from the fetched raw JD content. When a posting is re-fetched:

- hash unchanged → refresh `last_fetched_at`, keep `fresh`
- hash changed → insert new `job_snapshots` row, bump `current_snapshot_id` (the posting is a different version)
- fetch fails / 404 → `stale` → after confirm failure → `expired`

### RLS Note

`job_snapshots` has **no `user_id`** — it holds public job data (zero PII) and is intentionally **outside RLS** so a single extraction serves all users (the shared-cache invariant). `jobs` (user-scoped) and `applications.snapshot_id` remain RLS-protected by their existing policies.

---

## Migration 026: Auth Sessions + Login Lookup (S3)

```sql
-- File: migrations/026_create_auth_sessions.sql

CREATE TABLE auth_sessions (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    jti_hash    TEXT NOT NULL,              -- SHA-256 of the refresh-token jti (never raw)
    expires_at  TIMESTAMPTZ NOT NULL,       -- +7d at issue; matches refresh TTL
    revoked_at  TIMESTAMPTZ,                -- NULL = active; set by logout / refresh rotation
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_auth_sessions_user_id ON auth_sessions(user_id);
CREATE INDEX idx_auth_sessions_jti_hash ON auth_sessions(jti_hash);

-- Tenant isolation, consistent with every user-owned table (ENABLE + FORCE + policy).
ALTER TABLE auth_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_sessions FORCE ROW LEVEL SECURITY;

CREATE POLICY user_isolation ON auth_sessions
    USING (user_id = current_setting('app.user_id')::uuid);
```

### Purpose

Server-side session revocation store backing `POST /api/auth/logout` and refresh-token rotation (D8/D9: logout = server-side revoke, refresh = issue a new pair). `jti_hash` stores only the SHA-256 of the refresh token's `jti` — never the raw value (D12).

### Login Lookup (SECURITY DEFINER)

`auth_user_by_email(email)` is the narrow carve-out that lets login check credentials before any user context exists (RLS unset at login time). It is STABLE, returns at most one exact-match row, and is granted `EXECUTE` to `app_user` only.

```sql
CREATE OR REPLACE FUNCTION auth_user_by_email(p_email text)
RETURNS TABLE (id uuid, email text, password_hash text, name text)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT id, email, password_hash, name FROM users WHERE email = p_email LIMIT 1;
$$;

GRANT EXECUTE ON FUNCTION auth_user_by_email(text) TO app_user;
```

---

## Migration 027: Provider Name Constraint Lifted (S4)

Moves the LLM-provider capability gate from the schema into the **provider registry** (code in
`backend/app/llm/registry.py`, D19). From this migration on, the database accepts any lowercase
provider `name`; whether a name is actually callable is decided by the registry (whether an
adapter is registered for it), **not** by the database.

```sql
-- File: migrations/027_lift_llm_provider_name_check.sql

ALTER TABLE llm_providers DROP CONSTRAINT llm_providers_name_check;
ALTER TABLE llm_providers ADD CONSTRAINT llm_providers_name_lowercase
  CHECK (name = lower(name));
```

### Effect

- `llm_providers.name` no longer restricts inserts to `gemini/ollama/groq/openrouter`; it only
  enforces lowercase (so `"Anthropic"` and `"anthropic"` cannot coexist as two rows).
- Adding a new provider = registry entry (+ adapter for non-OpenAI-compatible protocols);
  **no further migrations**.
- `llm_chain` settings validation is registry-membership based (not the fixed 4-name list).
- Historical migration 005 is unchanged (forward-only).
