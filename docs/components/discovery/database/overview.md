# Discovery — Database Scope

Owns Telegram bot connections and message ingestion.

---

## Tables Owned

```
TABLE                   PURPOSE                          WRITES
───────────────────────────────────────────────────────────────
telegram_connections    Bot token + subscribed groups      CREATE, UPDATE, DELETE
telegram_messages       Raw Telegram message log           INSERT
```

---

## Tables Read

```
TABLE             READ BY              WHY
────────────────────────────────────────────────────
jobs              discovery            checks if job URL already exists
```

---

## Tables Written (INSERT only, no ownership)

```
TABLE             WRITER               WHY
────────────────────────────────────────────────────
audit_logs        discovery            logs discovery events (INSERT)
```

---

## Data Flow

```
CONNECT BOT:
  discovery → telegram_connections (INSERT bot_token, groups, status=connected)

RECEIVE MESSAGE:
  discovery → telegram_messages (INSERT chat_id, text, urls_found)

EXTRACT JOB URL:
  discovery → jobs (INSERT if new URL found)
  discovery → telegram_messages (UPDATE job_created=true, job_id)

DISCONNECT BOT:
  discovery → telegram_connections (UPDATE status=disconnected)

DELETE BOT:
  discovery → telegram_connections (DELETE by id)
```

---

## Relationships

```
users (1) ──────< (N) telegram_connections
users (1) ──────< (N) telegram_messages

telegram_messages (1) ──> (0..1) jobs
  (if URL found → job created)
```
