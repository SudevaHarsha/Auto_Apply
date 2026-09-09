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
