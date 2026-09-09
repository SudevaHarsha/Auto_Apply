# Backend API — FastAPI Endpoints

REST API consumed by the Chrome Extension and Next.js frontend.

---

## Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                    FASTAPI BACKEND                                │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  API Layer                                                 │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/auth/*                                         │  │   │
│  │  │  ├── POST   /register          (create user)        │  │   │
│  │  │  ├── POST   /login             (issue JWT)          │  │   │
│  │  │  ├── POST   /refresh           (refresh token)      │  │   │
│  │  │  └── GET    /me                (current user)       │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/profiles/*                                     │  │   │
│  │  │  ├── POST   /upload            (upload PDF)         │  │   │
│  │  │  ├── GET    /current           (active profile)     │  │   │
│  │  │  ├── PUT    /update            (edit JSONResume)    │  │   │
│  │  │  └── POST   /analyze           (trigger scoring)    │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/jobs/*                                         │  │   │
│  │  │  ├── GET    /discovered         (all discovered)    │  │   │
│  │  │  ├── POST   /manual             (add URL manually)  │  │   │
│  │  │  ├── GET    /pending             (awaiting review)  │  │   │
│  │  │  └── DELETE /{id}               (remove job)        │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/applications/*     (consumed by Extension)     │  │   │
│  │  │  ├── GET    /ready             (queued packages)    │  │   │
│  │  │  ├── GET    /{id}              (single package)     │  │   │
│  │  │  └── POST   /{id}/submit      (mark as submitted)  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/extensions/*       (consumed by Extension)     │  │   │
│  │  │  ├── POST   /{id}/fill        (start filling)      │  │   │
│  │  │  ├── POST   /{id}/screenshot  (capture proof)      │  │   │
│  │  │  └── POST   /{id}/submit      (mark submitted)     │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/llm/*                                          │  │   │
│  │  │  ├── GET    /providers          (user's providers)  │  │   │
│  │  │  ├── POST   /providers          (add provider)      │  │   │
│  │  │  ├── DELETE /providers/{id}     (remove provider)   │  │   │
│  │  │  └── POST   /test               (test a provider)   │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/telegram/*                                     │  │   │
│  │  │  ├── POST   /connect            (validate + start)  │  │   │
│  │  │  ├── DELETE /disconnect         (stop bot)          │  │   │
│  │  │  ├── GET    /status             (bot health)        │  │   │
│  │  │  └── GET    /groups             (subscribed groups)  │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/discord/*                                      │  │   │
│  │  │  ├── POST   /connect            (validate + start)  │  │   │
│  │  │  ├── DELETE /disconnect         (stop bot)          │  │   │
│  │  │  ├── GET    /status             (bot health)        │  │   │
│  │  │  └── GET    /servers            (subscribed servers) │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  │                                                            │   │
│  │  ┌──────────────────────────────────────────────────────┐  │   │
│  │  │  /api/checkpoints/*          (state persistence)      │  │   │
│  │  │  ├── GET    /pending            (paused jobs)       │  │   │
│  │  │  └── POST   /{id}/resume        (continue pipeline) │  │   │
│  │  └──────────────────────────────────────────────────────┘  │   │
│  └────────────────────────────────────────────────────────────┘   │
│                                                                   │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  Service Layer                                             │   │
│  │                                                            │   │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐   │   │
│  │  │  Profile     │ │  Job         │ │  Application     │   │   │
│  │  │  Service     │ │  Service     │ │  Service         │   │   │
│  │  └──────┬───────┘ └──────┬───────┘ └──────┬───────────┘   │   │
│  │         │                │                 │               │   │
│  │         └────────────────┼─────────────────┘               │   │
│  │                          │                                 │   │
│  │                          ▼                                 │   │
│  │               ┌─────────────────────┐                      │   │
│  │               │  Core Engine        │                      │   │
│  │               │  (hiring-agent-main │                      │   │
│  │               │   imported modules) │                      │   │
│  │               └─────────────────────┘                      │   │
│  └────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```
