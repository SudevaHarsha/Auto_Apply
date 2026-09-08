# Test Environment — Implemented (v1)

**Status:** ✅ **DONE — built and verified 2026-09-08.**
**Owner:** S1 follow-up · **Related:** `tasks.ps1`, `infra/docker-compose.dev.yml`,
`infra/docker-compose.test.yml`, `.env`, `.env.test.example`, `tests/parity/schema_parity.py`

---

## 1. Purpose

Give the project a **dedicated, disposable testing environment** that is fully separate
from the development database, so running the integration/parity suites can never touch,
wipe, or corrupt dev data. This mirrors the isolation an enterprise keeps between a
developer workstation (or a QA sandbox) and the test environment.

Today `-Target test-integration` and `-Target parity` reuse the **dev** `db` service
(`infra/docker-compose.dev.yml`) and do `down -v` — i.e. they destroy the dev volume on
every run. That is safe only while dev holds no real data. This design removes the coupling.

---

## 2. Why this shape (user decision log)

| Decision | Choice | Rationale |
|---|---|---|
| Test DB separate from dev? | **Yes** — own service, port, volume | Dev data must never be collateral |
| Implementation approach | **Option 1: dedicated `db_test` compose stack** | ~30 min, minimal moving parts vs. throwaway-container-per-run |
| Test DB on dev machine | Host port **5435** | 5432 occupied externally, 5434 = dev DB |
| `.env.test` in git? | **No** — gitignored; only `.env.test.example` is committed | Same policy as `.env`; CI/test targets fall back to the example |
| `parity` target | Points at the **test** stack; `parity-dev` added for ad-hoc dev drift checks | Recommendation B accepted |
| Teardown | Test stack wiped **before and after** each run | Disk always clean; next run fresh regardless |
| Enterprise "parallel-safe" hardening | **Out of scope for v1** (roadmap) | CI is single-job-today; per-run `down -v` is adequate |

---

## 3. Isolation model

The problem has three layers. v1 fixes the first two; the third is roadmap.

| Layer | Description | Enterprise equivalent | AutoApply v1 |
|---|---|---|---|
| **1. Dev-vs-test data** | Tests run against a DB that is not the dev DB | Separate QA/CI DB from developer DB | ✅ New `db_test` stack (port 5435, own volume) |
| **2. Ephemeral state** | Each run starts from a known-good, schema-only state, then tears down | CI provisions fresh DB per pipeline | ✅ `down -v` of the *test* stack before/after every run |
| **3. Parallel safety** | Concurrent runs / test workers cannot collide on the same database | Parallel CI matrices, `pytest-xdist` with per-worker DBs | ⚠️ Not in v1 — see §9 Roadmap |

Diagram:

```
            HOST :5434                      HOST :5435
   ┌───────────────────────┐      ┌───────────────────────┐
   │ infra (dev)           │      │ autoapply-test        │   <- project name
   │   db        p:5434    │      │   db_test   p:5435    │
   │   api       p:8000    │      │   <throwaway>         │
   │ volume pgdata         │      │ volume test_pgdata    │
   │ unchanged/permanent   │      │ wiped each run        │
   └───────────────────────┘      └───────────────────────┘
         .env (dev URLs)                  .env.test (TEST URLs)
```

Both stacks run the same `postgres:16` image; schemas are identical by construction
(parity enforces it). The only differences are the port, the volume, and the life cycle.

---

## 4. Proposed changes (what will be created on approval)

| File | Change |
|---|---|
| `infra/docker-compose.test.yml` | **New (built).** `name: autoapply-test` (top-level) so it is a separate compose project; service `db_test` mirroring `db`, bound to `${TEST_POSTGRES_PORT:-5435}:5432`, volume `test_pgdata`. No `api` service — tests only need Postgres today. |
| `.env.test.example` | **New (built).** Committed template: test URLs on port 5435. `.env.test` (gitignored) is a local copy, or the example is used as fallback. |
| `.gitignore` | `.env.test` added (mirrors `.env`). |
| `tasks.ps1` | `Load-Env -File` parameter; `Load-TestEnv` (`.env.test`, fallback `.env.test.example`); `Wait-Db -ComposeFile/-Service`; targets `test-integration`/`parity` now use the **test stack**; `parity-dev`, `test-env-up`, `test-env-down` added. |
| `tests/parity/schema_parity.py` | **Env-driven stack selection:** `PARITY_COMPOSE` + `PARITY_DB_SERVICE` (defaults = dev) so the golden `pg_dump` runs in either stack's container. |
| `tests/**` (tests code) | **No changes** — suites already read `MIGRATE_DATABASE_URL`/`DATABASE_URL` from the process env. |
| `ci.yml` | **No changes** needed — CI calls `tasks.ps1` targets, which now run on the test stack (fallback to `.env.test.example` in CI). |

### Example `infra/docker-compose.test.yml`

```yaml
name: autoapply-test

services:
  db_test:
    image: postgres:16
    environment:
      POSTGRES_USER: ${TEST_POSTGRES_USER:-autoapply}
      POSTGRES_PASSWORD: ${TEST_POSTGRES_PASSWORD:-autoapply}
      POSTGRES_DB: ${TEST_POSTGRES_DB:-autoapply}
    ports:
      - "${TEST_POSTGRES_PORT:-5435}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${TEST_POSTGRES_USER:-autoapply}"]
      interval: 5s
      retries: 10
    volumes:
      - test_pgdata:/var/lib/postgresql/data

volumes:
  test_pgdata:
```

### Example `.env.test`

```dotenv
# --- Test DB (project autoapply-test, host port 5435) ---
TEST_POSTGRES_USER=autoapply
TEST_POSTGRES_PASSWORD=autoapply
TEST_POSTGRES_DB=autoapply
TEST_POSTGRES_PORT=5435

DATABASE_URL=postgresql://app_user:changeme_in_production@localhost:5435/autoapply
MIGRATE_DATABASE_URL=postgresql://autoapply:autoapply@localhost:5435/autoapply
```

> Credential policy is identical to dev: placeholders only, no real secrets.
> `app_user` is the RLS-subject role for the suites; `autoapply` is the compose superuser
> the migration runner + scratch-DB harness needs (CREATEDB).

---

## 5. Lifecycle (task targets)

| Target | Stack | Behavior |
|---|---|---|
| `test-integration` | **test** (`autoapply-test`) | wipe → start `db_test` → migrate → run T1 → wipe/tear down. Dev untouched. |
| `parity` | **test** (`autoapply-test`) | wipe → start `db_test` → migrate → golden diff + docs matcher + parity tests → wipe/tear down. Dev untouched. |
| `parity-dev` | **dev** (`infra`) | start `db` (if down) → golden diff + docs matcher **against dev schema**. Does **not** migrate or wipe dev. Left running (it's dev). |
| `test-env-up` / `test-env-down` | **test** | manually bring the test cluster up (migrated) / stop it for interactive debugging. |
| `db-reset` / `dev-up` / `dev-down` / `migrate` | **dev** | unchanged — dev stack keeps working as before |

The variables that select the cluster (`DATABASE_URL`, `MIGRATE_DATABASE_URL`) are loaded
from `.env.test` (fallback `.env.test.example`) for test targets, and from `.env` for dev.
`schema_parity.py` picks the dump target via `PARITY_COMPOSE` / `PARITY_DB_SERVICE`
(defaults = dev) set by the target. No Python test code changes were required.

---

## 6. What this environment guarantees vs. not

**Guaranteed:**
- Running any test target can never modify the dev DB or its `pgdata` volume.
- Every test run starts from a freshly initialized schema (migrations applied in-run)
  and leaves no running containers behind.
- Test and dev schemas cannot drift silently (parity runs against the test stack and the
  committed golden dump).
- Drop-in for CI: the `integration` and `parity` jobs need zero CI-file edits.

**Not covered in v1:**
- Parallel-safe ephemeral DBs on a shared host (two runs at once = last-writer wins).
- Ephemeral DBs as an app feature (enterprise `CREATE DATABASE ... ON CONNECTION` per
  test session with unique suffixes).
- Secrets management above placeholder creds (real environments get real vaulting).
- Rate-limit/side-effect isolation (LLM keys, Telegram/Discord tokens) — that is the
  S4+ external-integration concern, not the DB.

---

## 7. Runbook

```powershell
# Fresh test run of T1 (integration) and parity — dev DB never touched:
.\tasks.ps1 -Target test-integration
.\tasks.ps1 -Target parity

# Ad-hoc drift check of your dev DB (read-only, does not migrate/wipe):
.\tasks.ps1 -Target parity-dev

# Interactive debugging on the test cluster (dev stack untouched):
.\tasks.ps1 -Target test-env-up
docker compose -f infra/docker-compose.test.yml exec db_test psql -U autoapply -d autoapply
.\tasks.ps1 -Target test-env-down
```

Conventions (same as S1 §13): migrations are **forward-only**; never edit an applied
migration; `down -v` on the test project only ever touches `autoapply-test_*` resources.

---

## 8. Verification plan (acceptance checks — results recorded below)

1. `docker volume ls` after a test run shows both `infra_pgdata` (dev) and
   `autoapply-test_test_pgdata` (test) exist; only the latter is recreated.
2. Run `-Target test-integration` twice: identical green results, dev DB untouched.
3. Run `-Target parity` on the test stack: golden diff clean, docs matcher green.
4. `psql` into port 5435 shows schema; port 5434 dev DB untouched.
5. Containers left running after a test run: none (`docker compose ls` clean).

**2026-09-08 results:** all five checks passed — test-integration and parity green on the
test cluster, parity-dev green against the dev schema, both volumes present, no leftover
containers after a test run.

---

## 9. Roadmap (beyond v1)

- **Ephemeral per-session DBs:** `db_test` stays up; each session create/drop
  `autoapply_test_<suffix>` so concurrent jobs never share a database. Optionally
  `pytest-xdist` with one DB per worker.
- **CI matrix isolation:** per-GHA-job ephemeral project (`-p autoapply-test-${{ github.run_id }}`)
  instead of a shared host port.
- **Secrets:** move test creds to CI secrets / `docker compose` `env_file` patterns once a
  real (non-local) test center exists.
- **API-under-test container:** add `db_test` += `api_test` (same image as dev) so E2E
  suites never start a server on the dev `api` port.

---

## 10. Decisions (final)

1. `.env.test` is **not committed** — gitignored; only `.env.test.example` is committed
   (test targets fall back to it automatically, including in CI).
2. `parity` targets the **test** stack; `parity-dev` was added for ad-hoc dev drift checks.
3. Test DB port is **5435**.