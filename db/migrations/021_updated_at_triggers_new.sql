-- File: migrations/021_updated_at_triggers_new.sql

CREATE TRIGGER update_settings_updated_at
    BEFORE UPDATE ON settings
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_rate_limit_state_updated_at
    BEFORE UPDATE ON rate_limit_state
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();