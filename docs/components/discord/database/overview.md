# Discord — Database Scope

Discord-specific tables for bot connections and message persistence.

---

## Tables Owned

```
TABLE                   PURPOSE                          WRITES
───────────────────────────────────────────────────────────────
discord_connections     Bot token + Discord settings      CREATE, UPDATE, DELETE
discord_messages        Message log (persistent)          INSERT
```

---

## Tables Read

```
TABLE             READ BY              WHY
───────────────────────────────────────────────────
jobs              discord              checks if job URL already exists
```

---

## Tables Written (INSERT only, no ownership)

```
TABLE             WRITER               WHY
───────────────────────────────────────────────────
audit_logs        discord              logs discovery events (INSERT)
```

---

## Schema Details

### discord_connections

```sql
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
```

**Fields:**
- `bot_token`: Encrypted Discord bot token (AES-256)
- `status`: Bot connection state
- `chat_mode`: Bot Mode (regex) or Agent Mode (LLM) - passed to chat_interface
- `notifications_enabled`: Master switch for push notifications
- `notification_events`: Which events trigger notifications
- `servers`: JSON array of subscribed server/channel IDs

### discord_messages

```sql
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
```

**Fields:**
- `server_id`: NULL for DMs (no server in DMs)
- `is_dm`: TRUE if direct message
- `direction`: inbound (user → bot) or outbound (bot → user)
- `urls_found`: Extracted URLs from message
- `job_created`: TRUE if URL was converted to a job

---

## Read Patterns

```
PATTERN                           SQL                          WHEN
─────────────────────────────────────────────────────────────────────
Get bot connection                SELECT * FROM discord_       On message received
  WHERE user_id = ?                connections                  (look up chat_mode)
                                   WHERE user_id = ?

Check if job exists               SELECT id FROM jobs         On URL extracted
  WHERE user_id = ?                WHERE user_id = ?
  AND url = ?                      AND url = ?

Get notification prefs            SELECT notifications_       On event occurs
                                   enabled, notification_      (before sending
                                   events FROM discord_        notification)
                                   connections
                                   WHERE user_id = ?
```

---

## Write Patterns

```
PATTERN                           SQL                          WHEN
─────────────────────────────────────────────────────────────────────
Connect bot                       INSERT INTO discord_        User connects bot
                                   connections                 (POST /api/discord/connect)
                                   (user_id, bot_token,
                                   bot_username, status)

Save inbound message              INSERT INTO discord_        Message received
                                   messages                    from user or channel
                                   (user_id, server_id,
                                   channel_id, text,
                                   direction='inbound')

Save outbound message             INSERT INTO discord_        Bot sends reply
                                   messages                    (via Discord API)
                                   (user_id, channel_id,
                                   text, direction='outbound')

Update chat mode                  UPDATE discord_             User switches mode
                                   connections                 (/mode bot or /mode agent)
                                   SET chat_mode = ?
                                   WHERE user_id = ?

Update notification prefs         UPDATE discord_             User changes prefs
                                   connections                 (/notifications on/off)
                                   SET notifications_enabled = ?
                                   SET notification_events = ?
                                   WHERE user_id = ?

Disconnect bot                    UPDATE discord_             User disconnects
                                   connections                 (DELETE /api/discord/disconnect)
                                   SET status = 'inactive'
                                   WHERE user_id = ?
```

---

## Data Flow

```
CONNECT BOT:
  discord adapter → Backend API → discord_connections (INSERT bot_token, servers, status=active)

RECEIVE MESSAGE (from user):
  discord adapter → discord_messages (INSERT is_dm, channel_id, text, direction='inbound')

RECEIVE MESSAGE (from channel):
  discord adapter → discord_messages (INSERT server_id, channel_id, text, urls_found)

EXTRACT JOB URL:
  discord adapter → Backend API → jobs (POST /api/jobs)
  discord adapter → discord_messages (UPDATE job_created=true, job_id)

SEND MESSAGE (bot reply):
  discord adapter → discord_messages (INSERT direction='outbound', text)

SWITCH MODE:
  discord adapter → discord_connections (UPDATE chat_mode)

UPDATE NOTIFICATIONS:
  discord adapter → discord_connections (UPDATE notification_events)

DISCONNECT BOT:
  discord adapter → Backend API → discord_connections (UPDATE status=inactive)

DELETE BOT:
  discord adapter → Backend API → discord_connections (DELETE by id)
```

---

## Relationships

```
users (1) ──────< (N) discord_connections
users (1) ──────< (N) discord_messages

discord_messages (1) ──> (0..1) jobs
  (if URL found → job created)
```
