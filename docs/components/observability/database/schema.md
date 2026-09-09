# Observability — Schema

> **Canonical source:** `docs/database/schema.md` — migration 012 (audit_logs), 018 (error_logs).

SQL for tables owned by the observability component.

---

## audit_logs

```sql
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

-- RLS
ALTER TABLE audit_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON audit_logs
    USING (user_id = current_setting('app.user_id')::uuid);

-- Immutability: prevent UPDATE and DELETE (except anonymization)
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
```

---

## error_logs

```sql
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
    retry_count INTEGER DEFAULT 0,
    next_action TEXT,
    stack_trace TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_error_logs_user_id ON error_logs(user_id);
CREATE INDEX idx_error_logs_component ON error_logs(component);
CREATE INDEX idx_error_logs_severity ON error_logs(severity);
CREATE INDEX idx_error_logs_job_id ON error_logs(job_id);
CREATE INDEX idx_error_logs_created_at ON error_logs(created_at);

-- RLS
ALTER TABLE error_logs ENABLE ROW LEVEL SECURITY;
CREATE POLICY user_isolation ON error_logs
    USING (user_id = current_setting('app.user_id')::uuid);

-- Immutability: prevent UPDATE and DELETE (except anonymization)
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
```

---

## Note: pipeline_runs has moved to core_engine

```
pipeline_runs is owned by core_engine (the pipeline runner).
See: docs/components/core_engine/database/schema.md
```
