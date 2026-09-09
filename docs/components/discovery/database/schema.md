# Discovery — Schema

> **Canonical source:** `docs/database/schema.md` — migration 010 (telegram_connections), 017 (telegram_messages).

SQL for tables owned by the discovery component.

---

## telegram_connections

```sql
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

## telegram_messages

```sql
CREATE TABLE telegram_messages (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    chat_id BIGINT NOT NULL,
    chat_title TEXT,
    message_id BIGINT NOT NULL,
    text TEXT,
    urls_found TEXT[] DEFAULT '{}',
    job_created BOOLEAN DEFAULT FALSE,
    job_id UUID REFERENCES jobs(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, chat_id, message_id)
);

CREATE INDEX idx_telegram_messages_user_id ON telegram_messages(user_id);
CREATE INDEX idx_telegram_messages_chat ON telegram_messages(user_id, chat_id);
```
