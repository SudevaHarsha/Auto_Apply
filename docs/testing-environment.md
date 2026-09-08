# Test Environment — Implemented (v3: per-run ephemeral DBs)

**Status:** ✅ ~built & verified 2026-09-08~ → **v3 implemented** (Option 1, enterprise pattern).
**Owner:** S1 follow-up · **Related:** `tasks.ps1`, `infra/docker-compose.test.yml`,
`infra/pgadmin/servers.json`, `db/per_run_db.py`, `.env`, `.env.test.example`,
`tests/parity/schema_parity.py`

---

## 1. Purpose

Give the project a **dedicated testing environment** that is fully separate from the
development database, so running the integration/parity suites can never touch, wipe, or
corrupt dev data.

**Evolution of the lifecycle model:**

| Version | Data lifecycle | Problem fixed |
|---|---|---|
| v1 | `db_test` stack wiped (`down -v`) before **and** after each run | Dev DB isolation, but nothing inspectable afterward |
| v2 | Persistent `db_test`; never wiped; data **accumulates** across runs | Inspectable, but dirty — cross-run contamination, not deterministic |
| **v3 (current)** | Persistent stack + baseline; each run uses a **disposable per-run DB** cloned from the baseline | Deterministic **and** inspectable — the enterprise-standard pattern |

---

## 2. Why this shape (user decision log)

| Decision | Choice | Rationale |
|---|---|---|
| Test DB separate from dev? | **Yes** — own compose project, port, volume | Dev data must never be collateral |
| Data lifecycle (v3) | **Per-run ephemeral DBs** (`CREATE DATABASE x TEMPLATE base`) | Clean = deterministic; stack = inspectable; matches how production Postgres teams provision test DBs |
| Base kept? | **Yes** — a migrated `autoapply` **baseline** on `db_test`, never touched by tests | Template source for the copy-on-write clones; clean schema anchor for parity |
| Test DB on dev machine | Host port **5435** | 5432 occupied externally, 5434 = dev DB |
| Inspect post-run | Keep the **most recent** per-run DB alive (`KEEP_LAST=1`); pgAdmin views it | Last run's data is still visible after the suite exits |
| `.env.test` in git? | **No** — gitignored; only `.env.test.example` is committed | Same policy as `.env`; CI/test targets fall back to the example |
| `parity` target | Points at the **test** stack; `parity-dev` added for ad-hoc dev drift checks | Recommendation B accepted |
| CI behavior | Same targets, ephemeral runner → fresh DB per job | Zero CI-file changes needed |
| Parallel "pytest-xdist" safety | **Enabled by design** — one DB per run, no shared mutable DB | Roadmap §9 objective now structurally satisfied |

---

## 3. Isolation model

| Layer | Description | Enterprise equivalent | AutoApply v3 |
|---|---|---|---|
| **1. Dev-vs-test data** | Tests run against a DB that is not the dev DB | Separate QA/CI DB from developer DB | ✅ Separate `autoapply-test` compose project (port 5435, own volume) |
| **2. Deterministic per-run data** | Each run starts from a known baseline, never accumulates | Fresh DB per pipeline / Testcontainers-per-test | ✅ Per-run clone of the migrated baseline; dropped after |
| **3. Parallel safety** | Concurrent runs / workers cannot collide | Parallel CI matrices, `pytest-xdist` per-worker DBs | ✅ Each run owns a unique DB — inherent isolation |

Diagram:

```
            HOST :5434                      HOST :5435               HOST :5050
   ┌───────────────────────┐      ┌───────────────────────┐    ┌─────────────┐
   │ infra (dev)           │      │ autoapply-test        │    │ pgAdmin     │
   │   db        p:5434    │      │   db_test   p:5435    │    │  (UI)       │
   │   api       p:8000    │      │   pgadmin  p:5050     │    │  Dev+Test   │
   │ volume pgdata         │      │ volume test_pgdata    │    └─────────────┘
   │ unchanged/permanent   │      └──────────────┬────────┘
   └───────────────────────┘         │ baseline `autoapply` (clean, migrated)
         .env (dev URLs)             │   ┌── per-run clone
                                     │   │  `db_test: autoapply`──> `app_test_<ts>` (disposable)
                                     │   └── run suite there, then DROP (keep newest for inspection)
                                          .env.test (TEST URLs)
```

Baseline `autoapply` holds the **schema only** (clean — tests never write to it). Each
`test-integration` run clones it copy-on-write into `app_test_<timestamp>`, runs the whole
suite against that clone, then drops all clones except the newest.

---

## 4. Components

| File | Change |
|---|---|
| `infra/docker-compose.test.yml` | `name: autoapply-test`; `db_test` (port 5435, `test_pgdata`); `pgadmin` (port 5050, `pgadmin_data`, preconfigured servers). No `api` — tests only need Postgres. |
| `infra/pgadmin/servers.json` | pgAdmin pre-registers `Dev DB (host 5434)` → `host.docker.internal:5434` and `Test DB (host 5435)` → `db_test:5432`, both as superuser `autoapply` (RLS-bypassing view, so all databases incl. clones are browsable). |
| `db/per_run_db.py` | Cluster helper: `ensure-baseline` (migrate if absent), `create` (clone via `TEMPLATE`), `cleanup` (drop all clones except newest), `list`. |
| `.env.test.example` | Test URLs on 5435 + `PGADMIN_*` defaults. `.env.test` (gitignored) is a local copy or fallback. |
| `tasks.ps1` | `Load-Env -File`/`Load-TestEnv`/`Wait-Db`; native calls wrapped in `Invoke-Check` (fixes PowerShell 5.1 `NativeCommandError` on docker stderr); `test-integration`/`parity` use per-run clones; `test-env-up`/`test-env-reset`/`test-env-down`. |
| `tests/parity/schema_parity.py` | Env-driven stack selection `PARITY_COMPOSE` + `PARITY_DB_SERVICE`; dumps the **baseline** `autoapply` DB (schema-only). |
| `tests/**` behavior | Tests read `MIGRATE_DATABASE_URL`/`DATABASE_URL` from the process env → they transparently run against whichever clone the target points them at. No code change needed. |

### The clone mechanism

PostgreSQL `CREATE DATABASE x TEMPLATE autoapply` is a **copy-on-write snapshot** of the
baseline schema — near-instant, no dump/restore. The clone inherits all tables, indexes,
RLS policies, triggers, and roles. `db/per_run_db.py` connects as the cluster superuser via
the **maintenance `postgres` DB** so it never locks the baseline template.

---

## 5. Lifecycle (task targets)

| Target | Stack | Behavior |
|---|---|---|
| `test-integration` | **test** | ensure stack+baseline → `CREATE DATABASE app_test_<ts> TEMPLATE autoapply` → point `DATABASE_URL` (app_user) **and** `MIGRATE_DATABASE_URL` (admin) at the clone → run T1+T2 → `cleanup` (drop all clones, keep newest). Baseline + stack stay up/clean. |
| `parity` | **test** | ensure stack + baseline → golden diff + docs matcher + parity tests **against the baseline** (schema-only). Leave running. |
| `parity-dev` | **dev** | golden diff + docs matcher against dev schema. No migrate/wipe. Left running. |
| `test-env-up` | **test** | `up -d` whole stack (`db_test` + `pgadmin`) + `ensure-baseline`. |
| `test-env-reset` | **test** | `down -v` (wipes `test_pgdata`+`pgadmin_data`), `up -d`, `ensure-baseline` — a pristine test cluster. |
| `test-env-down` | **test** | `down` (keeps volumes) for interactive debugging. |
| `db-reset` / `dev-up` / `dev-down` / `migrate` | **dev** | unchanged. |

> **Why `DATABASE_URL` must not be the superuser URL:** the RLS matrix connects as
> `app_user` (the RLS subject) via `DATABASE_URL`. Pointing it at the `autoapply` superuser
> would **bypass RLS** and break every isolation assertion. The target always builds the
> app-user clone URL from the app-user base, and the admin clone URL from the migrate base.

---

## 6. What this environment guarantees vs. not

**Guaranteed:**
- Running any test target can never modify the dev DB or its `pgdata` volume.
- Every integration run starts from a **deterministic, clean baseline** — tests can never
  see data left by a previous run (per-run DB, not accumulation).
- The stack stays **running and inspectable**; the newest per-run DB (`app_test_*`) is kept
  alive so you can poke at the last run's data in pgAdmin.
- The baseline schema cannot drift silently (parity dumps it against the golden file).
- Drop-in for CI: `integration`/`parity` jobs need zero CI edits; ephemeral runners get a
  fresh baseline+clone every job.

**Not covered (v3):**
- Cross-host/matrix clones with unique project names (single machine today). Structurally
  ready (one DB per run), but per-GHA-job project naming is future work.
- Persistent, seeded "demo" data set in the baseline (baseline stays schema-only).
- Secrets above placeholder creds (real environments get real vaulting).

---

## 7. Runbook

```powershell
# Deterministic integration run against a disposable per-run DB; baseline stays clean;
# the newest clone is kept for inspection. Dev DB never touched.
.\tasks.ps1 -Target test-integration

# Schema parity vs the baseline (clean) — PASS means no drift.
.\tasks.ps1 -Target parity

# Inspect the last run's data in a browser:
.\tasks.ps1 -Target test-env-up        # ensures db_test + pgadmin up (baseline migrated)
#   -> open http://localhost:5050      login: admin@autoapply.com / admin
#   -> servers: "Dev DB (host 5434)" and "Test DB (host 5435)"; DB password: autoapply
#   -> under the Test server, pick the `app_test_<latest>` database from the dropdown
#   -> the superuser role bypasses RLS, so every table is fully visible

# Ad-hoc drift check of your dev DB (read-only, no migrate/wipe):
.\tasks.ps1 -Target parity-dev

# Wipe the whole test cluster to pristine (baseline + clones + pgadmin config gone):
.\tasks.ps1 -Target test-env-reset

# Interactive debugging on the test cluster:
.\tasks.ps1 -Target test-env-up
docker compose -f infra/docker-compose.test.yml exec db_test psql -U autoapply -d autoapply
.\tasks.ps1 -Target test-env-down   # stops stack, keeps volumes
```

Conventions (same as S1 §13): migrations are **forward-only**; never edit an applied
migration; `down -v` on the test project only ever touches `autoapply-test_*` resources.
Per-run DBs are ephemeral by construction — only the newest is retained, explicitly for
inspection.

---

## 8. Verification plan (acceptance — results below)

1. `docker volume ls` shows `infra_pgdata` (dev) + `autoapply-test_test_pgdata` +
   `autoapply-test_pgadmin_data` (test).
2. `-Target test-integration` run twice: identical green (37/37), dev DB untouched; each
   run creates a new `app_test_*` clone and drops all but the newest.
3. `-Target parity` green (golden diff + docs matcher) against the baseline.
4. A bare `app_user` connection to a clone is fail-closed (`UndefinedObject` on unset
   `app.user_id`); the superuser view shows the last run's rows.
5. After a run the stack is left running; pgAdmin on 5050 lists both servers.

**2026-09-08 (v3) results:** run 1 → 37/37 (clone `app_test_...2302` kept). Run 2 →
37/37 (`...2318` kept, `...2302` dropped). parity PASS. Baseline stays clean. Stack
(db_test + pgadmin) left running. Lint clean.

---

## 9. Roadmap (beyond v3)

- **Per-GHA-job project naming:** `-p autoapply-test-${{ github.run_id }}` so CI matrices
  get isolated networks/ports, not just isolated DBs.
- **`pytest-xdist`:** one clone per worker (already one-DB-per-run, trivially extended to
  one per worker with a worker suffix).
- **Seeded baseline / golden dataset:** add a reproducible seed used by both dev and test.
- **API-under-test:** add `api_test` beside `db_test` for E2E without touching the dev port.
- **Auto-housekeeping:** a cron/reaper to `DROP` stale `app_test_*` clones older than N days.

---

## 10. Decisions (final)

1. `.env.test` is **not committed** — gitignored; only `.env.test.example` is committed.
2. `parity` targets the **test** stack (baseline); `parity-dev` for ad-hoc dev checks.
3. Test DB port is **5435**.
4. **v3 — per-run ephemeral DBs (Option 1):** the stack and baseline are persistent; each
   run clones `autoapply` → `app_test_<ts>`, runs against the clone, drops all but the
   newest. Deterministic + inspectable, matching how production Postgres teams provision
   test databases.
5. **v3 — role discipline:** the integration suite runs as `app_user` via `DATABASE_URL`;
   the target builds the app-user clone URL separately from the admin clone URL so RLS is
   never bypassed accidentally.
6. **v3 — `tasks.ps1` runs in `$ErrorActionPreference = "Continue"`** with explicit
   `Invoke-Check` guards on must-succeed steps, because PowerShell 5.1 treats native stderr
   (e.g. `docker compose up -d` on a running container) as a terminating error under
   `"Stop"`.
7. pgAdmin views the cluster as the `autoapply` superuser so all databases (baseline and
   clones) are browsable for inspection.
