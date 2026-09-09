# Chat Interface

The Chat Interface is how users interact with AutoApply. Shared between Web UI and Discord with two switchable modes.

---

## Overview

```
User sends message (Web UI or Discord)
        |
        v
+----------------------------------------------+
|  Mode Router                                  |
|                                               |
|  chat_mode = 'bot'   -> Bot Mode (0 tokens)  |
|  chat_mode = 'agent' -> Agent Mode (LLM)     |
+----------------------------------------------+
        |                                       
        v                                       
+----------------------------------------------+
|  Execute command or tool call                 |
+----------------------------------------------+
        |                                       
        v                                       
+----------------------------------------------+
|  Format response                              |
|  Web UI: React card  |  Discord: Embed card   |
+----------------------------------------------+
        |                                       
        v                                       
  Return to user
```

---

## Mode 1: Bot Mode (Zero Token Cost)

### How It Works

```
User message arrives
        |
        v
+----------------------------------------------+
|  REGEX PARSER                                |
|                                              |
|  Input: "score job abc-123"                  |
|                                              |
|  Pattern: /score\s+(?:job\s+)?([a-f0-9-]+)/i|
|  Match:   job_id = "abc-123"                 |
|  Action:  POST /api/jobs/abc-123/score       |
|                                              |
|  No LLM. Pure pattern matching.              |
|  Zero tokens consumed.                       |
+----------------------------------------------+
```

### Supported Commands

```
COMMAND                    PATTERN                                API CALL
---------------------------------------------------------------------------------
Show jobs                  /show\s+jobs/i                         GET /api/jobs
Show discovered            /show\s+discovered/i                   GET /api/jobs?status=discovered
Show approved              /show\s+approved/i                     GET /api/jobs?status=approved
Show rejected              /show\s+rejected/i                     GET /api/jobs?status=rejected

Score job                  /score\s+(?:job\s+)?([a-f0-9-]+)/i    POST /api/jobs/{id}/score
Approve job                /approve\s+(?:job\s+)?([a-f0-9-]+)/i  POST /api/jobs/{id}/approve
Reject job                 /reject\s+(?:job\s+)?([a-f0-9-]+)/i   POST /api/jobs/{id}/reject

Run pipeline               /run\s+(?:pipeline\s+)?([a-f0-9-]+)/i POST /api/pipeline/{id}/start
Resume pipeline            /resume\s+([a-f0-9-]+)/i              POST /api/checkpoints/{id}/resume

Show providers             /show\s+providers/i                    GET /api/llm/providers
Show status                /status/i                              GET /api/pipeline/status

Help                       /help/i                               (local response)
Switch to bot              /mode bot/i                            (local setting)
Switch to agent            /mode agent/i                          (local setting)
```

### Processing Flow

```python
def process_bot_message(message: str, user_id: str) -> dict:
    """Process user message in Bot Mode. Zero LLM tokens."""
    
    message = message.strip().lower()
    
    # Try each command pattern
    for cmd_name, cmd_config in COMMANDS.items():
        match = re.match(cmd_config["pattern"], message, re.IGNORECASE)
        if match:
            # Extract parameters from match groups
            params = extract_params(match, cmd_config)
            
            # Handle local commands (help, mode switch)
            if cmd_config["endpoint"] is None:
                return handle_local_command(cmd_name, params)
            
            # Call Backend API
            response = call_api(
                method=cmd_config["method"],
                endpoint=cmd_config["endpoint"].format(**params),
                query=cmd_config.get("params", {}),
                user_id=user_id
            )
            
            return format_response(cmd_name, response)
    
    # No pattern matched
    return {
        "type": "error",
        "text": "I don't understand that command. Type 'help' to see available commands."
    }
```

### Error Handling

```
SCENARIO                          RESPONSE
---------------------------------------------------------------------------
No command matched                 "I don't understand. Type 'help'."
Job not found                     "Job {id} not found."
Pipeline already running          "Pipeline already running for this job."
All providers exhausted           "All LLM providers failed. Check /providers."
Network error                     "Connection failed. Try again."
```

---

## Mode 2: Agent Mode (Flexible, Token Cost)

### How It Works

```
User message arrives
        |
        v
+----------------------------------------------+
|  LLM ROUTER                                 |
|                                              |
|  Send message + tool definitions to LLM      |
|  LLM decides which tools to call             |
|                                              |
|  Provider chain: Gemini -> Ollama -> Groq -> OpenRouter |
+----------------------------------------------+
        |
        v
+----------------------------------------------+
|  TOOL EXECUTION                              |
|                                              |
|  LLM returns tool calls:                     |
|  [                                           |
|    { "tool": "search_jobs", "args": {...} }, |
|    { "tool": "analyze_match", "args": {...} }|
|  ]                                           |
|                                              |
|  Execute each tool call via Backend API      |
+----------------------------------------------+
        |
        v
+----------------------------------------------+
|  RESPONSE GENERATION                         |
|                                              |
|  Send tool results back to LLM               |
|  LLM generates human-readable response       |
|                                              |
|  "Found 3 Python jobs. The best match is     |
|   Senior Dev at Acme (score 87/100).         |
|   Want me to run the pipeline?"              |
+----------------------------------------------+
```

### Tool Definitions (sent to LLM)

```python
TOOLS = [
    {
        "name": "search_jobs",
        "description": "Search for jobs. Can filter by status, query, or platform.",
        "parameters": {
            "query": "Search query (optional)",
            "status": "Filter by status: discovered, scored, approved, applying, applied, rejected, skipped, failed (optional)",
            "platform": "Filter by platform: greenhouse, lever, linkedin, indeed, workday, generic (optional)"
        },
        "api": "GET /api/jobs"
    },
    {
        "name": "analyze_match",
        "description": "Score how well a job matches the user's profile.",
        "parameters": {
            "job_id": "UUID of the job to analyze"
        },
        "api": "POST /api/jobs/{job_id}/score"
    },
    {
        "name": "approve_job",
        "description": "Approve a job and start the optimization pipeline.",
        "parameters": {
            "job_id": "UUID of the job to approve"
        },
        "api": "POST /api/jobs/{job_id}/approve"
    },
    {
        "name": "reject_job",
        "description": "Reject a job. It won't appear again.",
        "parameters": {
            "job_id": "UUID of the job to reject"
        },
        "api": "POST /api/jobs/{job_id}/reject"
    },
    {
        "name": "get_package",
        "description": "Get the application package (PDF, cover letter, field mappings) for an approved job.",
        "parameters": {
            "application_id": "UUID of the application"
        },
        "api": "GET /api/applications/{application_id}"
    },
    {
        "name": "list_providers",
        "description": "List all LLM providers and their status.",
        "parameters": {},
        "api": "GET /api/llm/providers"
    },
    {
        "name": "resume_pipeline",
        "description": "Resume a paused pipeline from a checkpoint.",
        "parameters": {
            "checkpoint_id": "UUID of the checkpoint"
        },
        "api": "POST /api/checkpoints/{checkpoint_id}/resume"
    }
]
```

### LLM System Prompt

```
You are AutoApply, an AI job application assistant.

You have access to these tools:
- search_jobs: Find jobs in the database
- analyze_match: Score how well a job matches the user's profile
- approve_job: Approve a job and start the optimization pipeline
- reject_job: Reject a job
- get_package: Get the application package for an approved job
- list_providers: Check LLM provider status
- resume_pipeline: Resume a paused pipeline

Rules:
1. Always search for jobs first before scoring
2. Show the user the score before approving
3. Ask for confirmation before approving
4. If a pipeline fails, suggest checking providers or resuming from checkpoint
5. Be concise. Use cards/embeds for job lists.
6. Never auto-approve. Always ask the user.
```

### Example Conversation

```
User:  Find Python jobs and score them

Agent: [calls search_jobs(query="Python")]
       Found 3 Python jobs:
       
       1. Senior Python Dev - Acme Corp (Not scored)
       2. Python Engineer - Meta (Score: 72/100)
       3. Backend Python - Startup (Not scored)
       
       Want me to score the unscored ones?

User:  Yes, score all 3

Agent: [calls analyze_match for each unscored job]
       Results:
       
       1. Senior Python Dev - Acme Corp: 87/100
          Strengths: Python, FastAPI, PostgreSQL
          Weaknesses: No Kubernetes experience
       
       3. Backend Python - Startup: 65/100
          Strengths: Python, Django
          Weaknesses: Missing AWS, too junior
       
       Best match: Acme Corp (87/100)
       Want me to approve it?

User:  Approve Acme

Agent: [calls approve_job(job_id="...")]
       Approved! Pipeline started for Senior Python Dev at Acme Corp.
       
       Pipeline steps:
       [x] JD Extraction
       [ ] Rubric Generation
       [ ] Scoring
       [ ] Optimization
       [ ] Package Generation
       
       I'll notify you when it's done.
```

### Processing Flow

```python
def process_agent_message(message: str, user_id: str) -> dict:
    """Process user message in Agent Mode. Uses LLM."""
    
    # 1. Build context
    context = build_context(user_id)
    
    # 2. Call LLM with tools
    llm_response = call_llm(
        system=AGENT_SYSTEM_PROMPT,
        message=message,
        tools=TOOLS,
        context=context
    )
    
    # 3. Execute tool calls
    tool_results = []
    for tool_call in llm_response.tool_calls:
        result = execute_tool(tool_call, user_id)
        tool_results.append(result)
    
    # 4. Generate final response
    final_response = call_llm(
        system=AGENT_SYSTEM_PROMPT,
        message=f"Tool results: {tool_results}",
        tools=None  # No more tools needed
    )
    
    return format_response("agent", final_response)
```

---

## Response Formats

### Web UI (React Cards)

```json
{
  "type": "job_list",
  "title": "Discovered Jobs",
  "jobs": [
    {
      "id": "abc-123",
      "title": "Senior Python Dev",
      "company": "Acme Corp",
      "score": 87,
      "status": "discovered",
      "actions": ["score", "approve", "reject"]
    }
  ]
}
```

### Discord (Embed Cards)

```
+--------------------------------------+
|  Discovered Jobs                     |
|                                      |
|  1. Senior Python Dev                |
|     Company: Acme Corp               |
|     Score: 87/100                    |
|     Status: Discovered               |
|                                      |
|     [Score] [Approve] [Reject]      |
+--------------------------------------+
```

---

## Mode Switching

### Commands

```
/mode bot     -> Switch to Bot Mode (zero tokens)
/mode agent   -> Switch to Agent Mode (LLM flexible)
```

### Storage

```sql
-- Web UI: stored in user settings
-- Discord: stored in discord_connections table
chat_mode TEXT DEFAULT 'bot' CHECK (chat_mode IN ('bot', 'agent'))
```

### Behavior

```
MODE SWITCH BEHAVIOR:
/mode bot:
  - All future messages parsed with regex
  - Zero token cost
  - Limited to predefined commands
  - Instant responses

/mode agent:
  - All future messages sent to LLM
  - Token cost per message
  - Flexible natural language
  - Variable response time
```

---

## Platform Differences

```
FEATURE              WEB UI                    DISCORD
--------------------------------------------------------------
Input                Browser textarea          DM or channel mention
Response             React component           Embed card
Buttons              HTML buttons              Discord buttons (if used)
History              Local state               discord_messages table
Notifications        Polling                   Push via bot
Mode switch          /mode command             /mode command
Auth                 JWT token                 Bot token (per user)
```

---

## Shared Components

```
Both Web UI and Discord share:
  - Mode Router (Bot/Agent logic)
  - Regex Parser (Bot Mode)
  - LLM Router (Agent Mode)
  - API Client (Backend calls)
  - Response Formatter (platform-specific output)

Platform-specific:
  - Web UI: React components, JWT auth, polling
  - Discord: Bot API, embed cards, push notifications
```
