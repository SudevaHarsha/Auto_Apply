# Discord — ER Diagram

---

## Tables

```
+---------------------+         +---------------------+
|  discord_connections|         |  discord_messages   |
+---------------------+         +---------------------+
| id (PK)             |         | id (PK)             |
| user_id (FK) ------+----+    | user_id (FK) ------+----+
| bot_token           |    |    | server_id           |    |
| bot_username        |    |    | server_name         |    |
| status              |    |    | channel_id          |    |
| chat_mode           |    |    | channel_name        |    |
| notifications_enabled|   |    | message_id          |    |
| notification_events |    |    | author_id           |    |
| servers (JSONB)     |    |    | is_dm               |    |
| created_at          |    |    | direction           |    |
| updated_at          |    |    | text                |    |
+---------------------+    |    | urls_found          |    |
                           |    | job_created         |    |
                           |    | job_id (FK) -------+--+ |
                           |    | created_at          |  |
                           |    +---------------------+  |
                           |                             |
                           |    +---------------------+  |
                           |    |       jobs           |  |
                           |    +---------------------+  |
                           +--->| id (PK)             |<-+
                                | user_id (FK)        |
                                | title               |
                                | company             |
                                | url                 |
                                | platform            |
                                 | source              |
                                 | status              |
                                 | score               |
                                 | freshness_state     |
                                 | current_snapshot_id |
                                 | content_hash        |
                                 | last_fetched_at     |
                                 | raw_message         |
                                 | created_at          |
                                 | updated_at          |
                                 +---------------------+

+---------------------+
|       users         |
+---------------------+
| id (PK)            |
| email              |
| password_hash      |
| name               |
| created_at         |
| updated_at         |
+---------------------+
         |
         +----< discord_connections (1:N)
         +----< discord_messages (1:N)
```

---

## Relationships

```
users (1) ──────< (N) discord_connections
  One user has many Discord bot connections
  FK: discord_connections.user_id → users.id

users (1) ──────< (N) discord_messages
  One user has many Discord messages
  FK: discord_messages.user_id → users.id

discord_messages (N) ──> (0..1) jobs
  One message may create zero or one job
  FK: discord_messages.job_id → jobs.id
  (only set when URL extracted → job created)
```

---

## Key Constraints

```
TABLE                   CONSTRAINT                          WHY
────────────────────────────────────────────────────────────────────
discord_connections     (no DB UNIQUE; one bot per user       Enforced at application layer, not in DDL
                        is an application-layer invariant)
discord_messages        UNIQUE(user_id, channel_id, message_id) Prevent duplicates
discord_messages        server_id NULLABLE                  DMs have no server
discord_messages        job_id NULLABLE                     Not all messages create jobs
```

---

## Indexes

```
TABLE                   INDEX                   PURPOSE
────────────────────────────────────────────────────────────────────
discord_connections     idx_discord_connections_uid    Fast lookup by user
discord_messages        idx_discord_messages_user_id   Fast lookup by user
discord_messages        idx_discord_messages_server    Fast lookup by server
discord_messages        idx_discord_messages_dm        Fast lookup for DMs
```
