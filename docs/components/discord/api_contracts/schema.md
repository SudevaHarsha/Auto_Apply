# Discord Adapter — API Contract

> **Owns:** Internal webhook `POST /api/webhooks/discord/message`
> **Auth:** Internal service-to-service (no user auth required)
> **Canonical source:** `docs/api_contracts/schema.md` §21

---

## Internal Webhook

### POST /api/webhooks/discord/message

Called by the Discord bot service when a new message arrives. This is an internal endpoint — not exposed to external consumers.

**Request (internal):**
```json
{
  "user_id": "uuid (required)",
  "server_id": "integer (null for DMs)",
  "server_name": "string (null for DMs)",
  "channel_id": "integer (required)",
  "channel_name": "string ('DM' for direct messages)",
  "message_id": "integer (required, Discord message ID)",
  "author_id": "integer (required, Discord user ID)",
  "is_dm": "boolean (required)",
  "direction": "inbound (required)",
  "text": "string (required, full message text)",
  "urls_found": ["string (array of extracted URLs)"]
}
```

**Response 200:**
```json
{
  "status": "processed",
  "jobs_created": "integer",
  "job_ids": ["uuid"]
}
```

**Side effects:**
- INSERT into `discord_messages` table
- For each URL found:
  - Detect platform from URL (greenhouse, lever, linkedin, indeed, workday, generic)
  - INSERT into `jobs` table with `status = discovered`, `source = discord`
  - UPDATE `discord_messages.job_created = true`, `discord_messages.job_id`
- Logs `job_discovered` to `audit_logs` for each new job

---

## Platform Detection

Same as Discovery (§discovery/api_contracts/schema.md):

| URL Pattern | Platform |
|-------------|----------|
| `greenhouse.io/jobs/*` | greenhouse |
| `lever.co/*` | lever |
| `linkedin.com/jobs/*` | linkedin |
| `indeed.com/viewjob/*` | indeed |
| `workday.com/*` | workday |
| (no pattern match) | generic |

---

## Data Flow

```
Discord message arrives
  → Discord Adapter extracts URLs
  → Calls POST /api/webhooks/discord/message
  → Backend API:
      1. INSERT into discord_messages
      2. For each URL:
         a. Detect platform
         b. INSERT into jobs (status=discovered, source=discord)
         c. UPDATE discord_messages (job_created=true, job_id)
      3. Log job_discovered to audit_logs
  → Trigger async JD Extraction pipeline
```

---

## What the Adapter Does (vs Chat Interface)

| Responsibility | Owner |
|----------------|-------|
| Receive Discord message event | Discord Adapter |
| Extract text, author_id, channel_id, server_id, is_dm | Discord Adapter |
| Convert to standard format | Discord Adapter |
| Call chat_interface.process_message() | Discord Adapter |
| Parse commands (regex/LLM) | Chat Interface |
| Call LLM | Chat Interface |
| Execute API calls | Chat Interface |
| Format business logic responses | Chat Interface |
| Convert response to Discord embed | Discord Adapter |
| Send embed via Discord API | Discord Adapter |

---

## Discord-Specific Features

| Feature | Description |
|---------|-------------|
| Bot token validation | Discord API `@me` endpoint |
| Server/channel subscription | Manage which servers the bot listens to |
| Push notifications | Event-driven, not polling |
| DM vs server channel | Different handling for DMs vs channels |
| Discord embed formatting | Rich embeds for job lists and scores |
| Bot lifecycle | Start/stop per user |

---

## Isolation Model

```
User A's bot → only sees → User A's servers/channels
User B's bot → only sees → User B's servers/channels

No cross-user data leakage.
Each bot token is unique per user.
Each bot is invited to servers by its owner only.
```

---

## Audit Actions

| Event | Audit Action | Resource Type |
|-------|-------------|---------------|
| Message received | (none, logged to discord_messages) | — |
| Job created from URL | `job_discovered` | job |
| Bot connected | `discord_connected` | discord |
| Bot disconnected | `discord_disconnected` | discord |
