# Frontend — Database Scope

No tables owned. Reads data via Backend API for UI rendering.

---

## Tables Displayed

```
TABLE                UI COMPONENT                    READS VIA
───────────────────────────────────────────────────────────────
users                ProfileMenu, SettingsPage        GET /api/auth/me
profiles             ProfilePage, UploadResume        GET /api/profiles/current
user_profiles        UserProfilePage                  GET /api/user-profiles
jobs                 JobBoard, JobCard                GET /api/jobs?status=discovered
applications         ApplicationsTable, AppCard       GET /api/applications/ready
llm_providers        LLMProvidersPage                 GET /api/llm/providers
telegram_connections TelegramPage                     GET /api/telegram/status
checkpoints          PipelineStatus                   GET /api/checkpoints/pending
```

---

## Access Pattern

```
Frontend never touches the database directly
All data fetched via Backend API → Database
```
