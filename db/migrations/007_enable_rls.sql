-- File: migrations/007_enable_rls.sql
-- NOTE (D1, doc divergence): the doc '007' also references discord_connections /
-- discord_messages with ENABLE RLS + user_isolation policies, but those tables are
-- created only in migration 022. Those lines are moved to 022 to keep the doc's
-- ordering runnable. Final schema identical to doc intent.

-- Enable RLS on all existing tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE jobs ENABLE ROW LEVEL SECURITY;
ALTER TABLE applications ENABLE ROW LEVEL SECURITY;
ALTER TABLE llm_providers ENABLE ROW LEVEL SECURITY;
ALTER TABLE checkpoints ENABLE ROW LEVEL SECURITY;

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
