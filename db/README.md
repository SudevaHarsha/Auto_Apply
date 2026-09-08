# db

Migrations live in `db/migrations/`, numbered `001_…` through `025_…`, matching
`docs/database/schema.md` (source of truth).

## Apply

    python db/run_migrations.py

Connects via `MIGRATE_DATABASE_URL` (dev default is the compose superuser). The
app itself must use `DATABASE_URL` as `app_user` so RLS applies.

Or via tasks:

    pwsh tasks.ps1 -Target migrate        # apply to a fresh dev DB

## Rules

- **Forward-only.** Never edit an applied migration; fix forward with a new one.
- Migrations are written to run in order on a fresh DB. Re-applying to a
  non-fresh DB fails loudly (e.g. `CREATE TABLE`), by design.
- Schema/RLS invariants are verified after every apply by `db/run_migrations.py`
  (`verify()`) and cross-checked by `tests/parity/schema_parity.py` (golden
  pg_dump diff + docs inventory matcher).

## S1 documented divergences (D1–D4)

These reconcile ordering/completeness gaps in `docs/database/schema.md` without
changing the documented final schema (documented in the migration file headers):

- **D1** — `007` referenced `discord_*` tables before `022` created them; the
  ENABLE + `user_isolation` policy block moved into `022`.
- **D2** — `023` FORCEd RLS on `user_profiles` before `024` created it; the
  FORCE line moved into `024`.
- **D3** — `CREATE ROLE app_user` is cluster-wide and outlives `DROP DATABASE`;
  wrapped in an idempotent guard.
- **D4** — docs gave `user_profiles` FORCE RLS but no ENABLE and no policy
  (it would be wholly inaccessible); `024` adds ENABLE + FORCE + policy.

Net final state: **20 tables, 37 `idx_*` indexes, 19/19 RLS enabled/forced,
21 policies, `job_snapshots` RLS-exempt** (2 pairs on discord tables, both
policies from the docs; `user_profiles` policy is the D4 addition).