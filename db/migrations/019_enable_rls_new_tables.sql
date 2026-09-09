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
