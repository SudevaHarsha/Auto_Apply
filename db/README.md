# db

Migrations live in `db/migrations/`, numbered `001_…` through `025_…`, matching
`docs/database/schema.md` (source of truth).

Rules:
- Forward-only. Never edit an applied migration; fix forward with a new one.
- Applied idempotently; migration parity is verified by `tests/parity`.

`migrations/` is filled in S1 (`plans/components/foundation.md`).