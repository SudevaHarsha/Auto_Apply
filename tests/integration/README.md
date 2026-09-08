# Integration tests (T1 + T2)

Run against the **isolated test stack** (`db_test`, port 5435) — never dev/prod. Each
`test-integration` run executes against a **disposable per-run clone** of the clean baseline
(`app_test_<ts>`), so it is deterministic run-over-run while the stack stays up for
inspection. See `docs/testing-environment.md` §3/§5.

```powershell
.\tasks.ps1 -Target test-integration   # clone baseline -> run all tests -> drop (keep newest)
.\tasks.ps1 -Target parity             # schema-parity + golden diff + docs matcher vs baseline
```

| File | Suite | Covers |
|---|---|---|
| `test_migrations.py` | T1 | forward + re-idempotent migrations on fresh DB; counts tables/indexes/RLS/policies |
| `test_rls_matrix.py` | T2 | cross-user RLS isolation on the 19 policy tables, snapshot shared-read, rollback, D5 default-denied, snapshot concurrency, DbContext |
| `test_ownership_guard.py` | T2 | static ownership map: repo `owns` sets ⇄ `OWNERSHIP` canonical map; no cross-repo table use in code |

## RLS credentials
T2 connects as **`app_user`** (the runtime role, never the superuser/migrator). `DATABASE_URL`
comes from `.env.test` (loaded by `tasks.ps1`); migrations run as `autoapply` using
`MIGRATE_DATABASE_URL`.

## D5 — test-vs-runtime divergence (recorded)
The original T2 sketch wanted a cross-user query "WITHOUT `SET LOCAL`" to fail and "WITH it" to pass.
The migrations' policies are `user_id = current_setting('app.user_id')::uuid` (**no `missing_ok`**),
so on a fresh session where `app.user_id` was never registered, a bare `app_user` connection
raises `UndefinedObject` ("unrecognized configuration parameter") — a **fail-closed error**, not the
NULL-compare the sketch assumed. Postgres only returns NULL for `current_setting('app.user_id', true)`
once the GUC has been set in that session.

Both safe paths are asserted by `test_default_denied_without_identity`:
- **WITHOUT (fail-closed):** bare connection, `SELECT count(*) FROM settings` raises `UndefinedObject`.
- **WITH explicit NULL identity (default-denied):** `DbContext(None)` maps to the zero-UUID sentinel
  (`NO_USER`) via `set_config` → `user_id = '0000…0'::uuid` matches no row → 0 rows. (Two attempts
  documented otherwise: `set_config(..., NULL, true)` stores an **empty string** GUC and `''::uuid`
  raises; a never-set GUC raises `UndefinedObject`. The sentinel is the only deterministic 0-row path.)

Runtime `DbContext` *always* sets the setting (docs mandate), so identity-less paths only occur via
`DbContext(None)`, never a bare connection.

No product behaviour contradicts `docs/**`; the test doubles as the guard that a stray identity-less
connection cannot read policy-table rows (it fails loudly instead).