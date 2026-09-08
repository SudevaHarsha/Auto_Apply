# AutoApply

Autonomous job-application agent. See `plans/` (sibling of this repo) for the
implementation plan (S0–S20), test plan (T0–T20), and per-component details.

## Runtime

Docker-first. Development: `.\tasks.ps1 -Target dev-up` (backend + postgres in
containers via `infra/docker-compose.dev.yml`). Production stack is finalized in
S19 per `docs/architecture/deployment.md`.

## Tooling

- Python >= 3.12 (venv in `.venv`)
- Task runner: `tasks.ps1` (machine has no `make`) — targets:
  `lint`, `test`, `dev-up`, `dev-down`, `test-integration`, `test-e2e`, `parity`
- CI mirrors these targets; log drift between the two is a defect

## Layout

- `backend/` — FastAPI service
- `frontend/` — Next.js dashboard (S18)
- `extension/` — Chrome MV3 add-on (S15)
- `db/migrations/` — 001–025 (S1)
- `infra/` — compose files
- `vendor/hiring_agent/` — vendored `hiring-agent-main`, **never modified** (I9)
  provenance + hash lock in `scripts/`