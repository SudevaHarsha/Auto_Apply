# Chat Interface — ER Diagram

Chat Interface is stateless. No tables owned, no ER diagram.

---

## Dependency Diagram

```
Chat Interface reads from multiple tables but owns none:

+-------------------+
| discord_connections| <--- reads chat_mode (Discord users)
+-------------------+
         |
         v
+-------------------+
|     settings      | <--- reads chat_mode (Web UI users)
+-------------------+
         |
         v
+-------------------+     +-------------------+
|       jobs        | <---|   applications    |
+-------------------+     +-------------------+
         |                        |
         v                        v
+-------------------+     +-------------------+
|  llm_providers    |     |   checkpoints     |
+-------------------+     +-------------------+

All writes go through Backend API endpoints.
Chat Interface does not write directly to any table.
```

---

## Data Flow

```
User Message
      |
      v
[Chat Interface]
      |
      |-- Read: discord_connections.chat_mode or settings.chat_mode
      |
      |-- Process: Bot Mode (regex) or Agent Mode (LLM)
      |
      v
[Backend API Endpoints]
      |
      |-- POST /api/jobs/{id}/score
      |-- POST /api/jobs/{id}/approve
      |-- GET  /api/jobs
      |-- GET  /api/llm/providers
      |-- etc.
      |
      v
[Database Tables]
      |
      |-- jobs (score, status updated)
      |-- pipeline_runs (created)
      |-- checkpoints (created)
      |-- etc.
```
