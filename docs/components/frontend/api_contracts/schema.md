# Frontend — API Contract

> **Consumes:** the dashboard subset of `/api/*` endpoints via browser (Next.js App Router)
> **Auth:** JWT token in httpOnly cookie (shared with Extension)
> **Canonical source:** `docs/api_contracts/schema.md` — all sections

---

## Endpoint Groups Consumed

### Auth (§7)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| POST /api/auth/register | POST | No | /login |
| POST /api/auth/login | POST | No | /login |
| POST /api/auth/refresh | POST | No | (automatic) |
| GET /api/auth/me | GET | Yes | (all pages) |

---

### Profile Management (§8)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| POST /api/profiles/upload | POST | Yes | /dashboard/profile |
| GET /api/profiles | GET | Yes | /dashboard/profile |
| GET /api/profiles/current | GET | Yes | /dashboard/profile |
| PUT /api/profiles/{id} | PUT | Yes | /dashboard/profile |
| POST /api/profiles/{id}/analyze | POST | Yes | /dashboard/profile |

---

### Job Management (§9)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/jobs | GET | Yes | /dashboard/jobs |
| GET /api/jobs/{id} | GET | Yes | /dashboard/jobs |
| POST /api/jobs/manual | POST | Yes | /dashboard/jobs |
| POST /api/jobs/{id}/score | POST | Yes | /dashboard/jobs |
| POST /api/jobs/{id}/approve | POST | Yes | /dashboard/jobs |
| POST /api/jobs/{id}/reject | POST | Yes | /dashboard/jobs |
| DELETE /api/jobs/{id} | DELETE | Yes | /dashboard/jobs |

---

### Application Management (§10)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/applications/ready | GET | Yes* | /dashboard/history |
| GET /api/applications/{id} | GET | Yes* | /dashboard/history |
| POST /api/applications/{id}/submit | POST | Yes* | /dashboard/history |

> `Yes*` = JWT required; Extension uses dedicated API key for server-to-server calls.

---

### LLM Provider Management (§12)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/llm/providers | GET | Yes | /dashboard/providers |
| POST /api/llm/providers | POST | Yes | /dashboard/providers |
| DELETE /api/llm/providers/{id} | DELETE | Yes | /dashboard/providers |
| POST /api/llm/test | POST | Yes | /dashboard/providers |

---

### Telegram Management (§13)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| POST /api/telegram/connect | POST | Yes | /dashboard/telegram |
| DELETE /api/telegram/disconnect | DELETE | Yes | /dashboard/telegram |
| GET /api/telegram/status | GET | Yes | /dashboard/telegram |
| GET /api/telegram/groups | GET | Yes | /dashboard/telegram |

---

### Discord Management (§14)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| POST /api/discord/connect | POST | Yes | /dashboard/discord |
| DELETE /api/discord/disconnect | DELETE | Yes | /dashboard/discord |
| GET /api/discord/status | GET | Yes | /dashboard/discord |
| GET /api/discord/servers | GET | Yes | /dashboard/discord |

---

### Checkpoint Management (§15)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/checkpoints/pending | GET | Yes | /dashboard/paused |
| POST /api/checkpoints/{id}/resume | POST | Yes | /dashboard/paused |

---

### Pipeline Management (§16)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/pipeline/status | GET | Yes | /dashboard/history |
| POST /api/pipeline/{id}/start | POST | Yes | /dashboard/jobs |

---

### Settings (§17)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/settings | GET | Yes | (all pages) |
| PUT /api/settings | PUT | Yes | (all pages) |

---

### User Profiles (§23)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/user-profiles | GET | Yes | /dashboard/user-profile |
| PUT /api/user-profiles | PUT | Yes | /dashboard/user-profile |

---

### Audit & Error Logs (§18, §19)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/audit | GET | Yes | /dashboard/audit |
| GET /api/audit/{id} | GET | Yes | /dashboard/audit |
| GET /api/errors | GET | Yes | /dashboard/errors |
| GET /api/errors/{id} | GET | Yes | /dashboard/errors |

---

### Evidence (§20)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| POST /api/evidence | POST | Yes | /dashboard/evidence |
| GET /api/evidence/{id} | GET | Yes | /dashboard/evidence |

---

### Health Check (§22)

| Endpoint | Method | Auth | Page |
|----------|--------|------|------|
| GET /api/health | GET | No | (status page) |

---

## Page-to-Endpoint Mapping

| Page | Primary Endpoints |
|------|-------------------|
| /dashboard/profile | profiles/upload, profiles/current, profiles/{id}, profiles/{id}/analyze |
| /dashboard/user-profile | user-profiles |
| /dashboard/jobs | jobs, jobs/{id}, jobs/manual, jobs/{id}/score, jobs/{id}/approve, jobs/{id}/reject |
| /dashboard/paused | checkpoints/pending, checkpoints/{id}/resume |
| /dashboard/history | applications/ready, applications/{id}, pipeline/status |
| /dashboard/evidence | evidence, evidence/{id} |
| /dashboard/audit | audit, audit/{id} |
| /dashboard/errors | errors, errors/{id} |
| /dashboard/providers | llm/providers, llm/test |
| /dashboard/health | llm/providers (health display) |
| /dashboard/telegram | telegram/connect, telegram/disconnect, telegram/status, telegram/groups |
| /dashboard/discord | discord/connect, discord/disconnect, discord/status, discord/servers |
| /dashboard/extension | (Extension status display, no direct API) |

---

## Audit Actions

| Endpoint | Audit Action | Resource Type |
|----------|-------------|---------------|
| POST /profiles/upload | `profile_uploaded` | profile |
| POST /profiles/{id}/analyze | `profile_scored` | profile |
| POST /jobs/manual | `job_discovered` | job |
| POST /jobs/{id}/score | `job_scored` | job |
| POST /jobs/{id}/approve | `job_approved` | job |
| POST /jobs/{id}/reject | `job_rejected` | job |
| DELETE /jobs/{id} | `job_rejected` | job |
| POST /applications/{id}/submit | `application_submitted` | application |
| POST /llm/providers | `llm_provider_added` | llm_provider |
| DELETE /llm/providers/{id} | `llm_provider_removed` | llm_provider |
| POST /llm/test | (provider test event) | llm_provider |
| POST /telegram/connect | `telegram_connected` | telegram |
| DELETE /telegram/disconnect | `telegram_disconnected` | telegram |
| POST /discord/connect | `discord_connected` | discord |
| DELETE /discord/disconnect | `discord_disconnected` | discord |
| POST /checkpoints/{id}/resume | `pipeline_resumed` | checkpoint |
| POST /pipeline/{id}/start | `pipeline_started` | pipeline_run |
| PUT /settings | `settings_updated` | settings |
