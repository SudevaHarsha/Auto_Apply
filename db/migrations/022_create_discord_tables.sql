-- File: migrations/022_create_discord_tables.sql
-- NOTE (D1, doc divergence): the doc's migration 007 also contained the ENABLE RLS
-- + user_isolation policy block below (moved here) because the discord tables do not
-- exist until this migration. 022's own RLS block is kept verbatim from the doc.
-- Net effect: discord_connections / discord_messages each end with two policies
-- (user_isolation + *_isolated), identical to the doc's stated intent.

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

-- RLS (moved from doc migration 007, D1)
ALTER TABLE discord_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_isolation ON discord_connections
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY user_isolation ON discord_messages
    USING (user_id = current_setting('app.user_id')::uuid);

-- RLS (verbatim from doc migration 022)
ALTER TABLE discord_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE discord_messages ENABLE ROW LEVEL SECURITY;

CREATE POLICY discord_connections_isolated ON discord_connections
    USING (user_id = current_setting('app.user_id')::uuid);

CREATE POLICY discord_messages_isolated ON discord_messages
    USING (user_id = current_setting('app.user_id')::uuid);