# Discovery — API Contract

> **Owns:** Internal webhook `POST /api/webhooks/telegram/message`
> **Auth:** Internal service-to-service (no user auth required)
> **Canonical source:** `docs/api_contracts/schema.md` §21

---

## Internal Webhook

### POST /api/webhooks/telegram/message

Called by the Telegram bot service when a new message arrives. This is an internal endpoint — not exposed to external consumers.

**Request (internal):**
```json
{
  "user_id": "uuid (required)",
  "chat_id": "integer (required, Telegram chat ID)",
  "chat_title": "string (required)",
  "message_id": "integer (required, Telegram message ID)",
  "text": "string (required, full message text)",
  "urls_found": ["string (array of extracted URLs)"],
  "attachments": ["string (array of attachment URLs)"]
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
- INSERT into `telegram_messages` table
- For each URL found:
  - Detect platform from URL (greenhouse, lever, linkedin, indeed, workday, generic)
  - INSERT into `jobs` table with `status = discovered`, `source = telegram`
  - UPDATE `telegram_messages.job_created = true`, `telegram_messages.job_id`
- Logs `job_discovered` to `audit_logs` for each new job

---

## Platform Detection

| URL Pattern | Platform |
|-------------|----------|
| `greenhouse.io/jobs/*` | greenhouse |
| `lever.co/*` | lever |
| `linkedin.com/jobs/*` | linkedin |
| `indeed.com/viewjob/*` | indeed |
| `workday.com/*` | workday |
| `boards.greenhouse.io/*` | greenhouse |
| `jobs.lever.co/*` | lever |
| (no pattern match) | generic |

---

## Data Flow

```
Telegram message arrives
  → Discovery extracts URLs
  → Calls POST /api/webhooks/telegram/message
  → Backend API:
      1. INSERT into telegram_messages
      2. For each URL:
         a. Detect platform
         b. INSERT into jobs (status=discovered, source=telegram)
         c. UPDATE telegram_messages (job_created=true, job_id)
      3. Log job_discovered to audit_logs
  → Trigger async JD Extraction pipeline
```

---

## Isolation Model

```
User A's bot → only sees → User A's groups/channels
User B's bot → only sees → User B's groups/channels

No cross-user data leakage.
Each bot token is unique per user.
Each bot is added to groups by its owner only.
```

---

## Audit Actions

| Event | Audit Action | Resource Type |
|-------|-------------|---------------|
| Message received | (none, logged to telegram_messages) | — |
| Job created from URL | `job_discovered` | job |
| Bot connected | `telegram_connected` | telegram |
| Bot disconnected | `telegram_disconnected` | telegram |
