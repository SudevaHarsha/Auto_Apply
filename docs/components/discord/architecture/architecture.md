# Discord Adapter

Thin adapter connecting Discord to the Chat Interface. No logic duplication.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    DISCORD ADAPTER                                │
│                                                                   │
│  Transport layer only. Core logic lives in chat_interface.        │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Bot Lifecycle                                             │   │
│  │                                                            │   │
│  │  On connect:                                               │   │
│  │  ├── Validate bot token via Discord API                    │   │
│  │  ├── Start bot instance                                    │   │
│  │  └── Register message handlers                             │   │
│  │                                                            │   │
│  │  On disconnect:                                            │   │
│  │  ├── Stop bot instance                                     │   │
│  │  └── Clean up handlers                                     │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Message Handling                                          │   │
│  │                                                            │   │
│  │  Discord event arrives                                     │   │
│  │        |                                                   │   │
│  │        v                                                   │   │
│  │  ┌──────────────────────────────────────────────────┐     │   │
│  │  │  Adapter: Convert Discord event → standard input  │     │   │
│  │  └──────────────────────────────────────────────────┘     │   │
│  │        |                                                   │   │
│  │        v                                                   │   │
│  │  ┌──────────────────────────────────────────────────┐     │   │
│  │  │  Chat Interface: Process message (Bot or Agent)   │     │   │
│  │  │  (core logic, same as Web UI)                     │     │   │
│  │  └──────────────────────────────────────────────────┘     │   │
│  │        |                                                   │   │
│  │        v                                                   │   │
│  │  ┌──────────────────────────────────────────────────┐     │   │
│  │  │  Adapter: Convert response → Discord embed        │     │   │
│  │  └──────────────────────────────────────────────────┘     │   │
│  │        |                                                   │   │
│  │        v                                                   │   │
│  │  Send embed to Discord                                    │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

---

## What the Adapter Does

```
INBOUND (Discord → Chat Interface):
  1. Receive Discord message event
  2. Extract: text, author_id, channel_id, server_id, is_dm
  3. Convert to standard format: { text, user_id, context }
  4. Call chat_interface.process_message()

OUTBOUND (Chat Interface → Discord):
  1. Receive response from chat_interface: { type, data }
  2. Convert to Discord embed format
  3. Send via Discord API
```

---

## What the Adapter Does NOT Do

```
- Parse commands (chat_interface handles this)
- Call LLM (chat_interface handles this)
- Execute API calls (chat_interface handles this)
- Format business logic responses (chat_interface handles this)
```

---

## Discord-Specific Features

```
These are Discord-only, not in chat_interface:

1. Bot token validation (Discord API)
2. Server/channel subscription management
3. Push notifications (event-driven, not polling)
4. DM vs server channel handling
5. Discord embed formatting
6. Bot lifecycle (start/stop per user)
```

---

## Message Flow

```
Discord DM: "score job abc-123"
        |
        v
[Discord Adapter]
  - Extract: text="score job abc-123", author_id=123, is_dm=true
  - Convert: { text: "score job abc-123", user_id: "uuid-from-author" }
        |
        v
[Chat Interface - Bot Mode]
  - Regex match: /score\s+(?:job\s+)?([a-f0-9-]+)/i
  - Execute: POST /api/jobs/abc-123/score
  - Return: { type: "job_score", data: { id, title, score } }
        |
        v
[Discord Adapter]
  - Convert to embed:
    {
      title: "Job Scored",
      fields: [
        { name: "Job", value: "Senior Python Dev" },
        { name: "Score", value: "87/100" }
      ]
    }
  - Send via Discord API
```

---

## Schema

discord_connections stores Discord-specific settings:
- bot_token (encrypted)
- chat_mode (bot/agent) - passed to chat_interface
- notifications_enabled
- notification_events
- servers (subscribed channels)

discord_messages stores message history:
- is_dm
- direction (inbound/outbound)
- All message metadata

chat_interface reads chat_mode from discord_connections to determine processing mode.
