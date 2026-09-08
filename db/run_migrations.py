"""S1 migration runner (psycopg3).

Applies db/migrations/*.sql in lexical order, one transaction per file, then
verifies the resulting schema against the documented invariants
(20 tables, 37 idx_* indexes, 19/19 RLS enabled/forced, 21 policies,
job_snapshots RLS-exempt).

Connection: MIGRATE_DATABASE_URL env var
(default: postgresql://autoapply:autoapply@localhost:5432/autoapply — the dev
compose superuser; the app runtime uses DATABASE_URL as app_user instead).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import psycopg

MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"
DEFAULT_MIGRATE_URL = "postgresql://autoapply:autoapply@localhost:5432/autoapply"

# Documented invariants (docs/database/schema.md), reconciled for S1 divergences:
#   D4 adds ENABLE+FORCE+policy for user_profiles  -> 21 policies, 19 RLS tables.
EXPECTED_TABLES = 20
EXPECTED_IDX = 37
EXPECTED_RLS_TABLES = 19
EXPECTED_POLICIES = 21
RLS_FREE_TABLE = "job_snapshots"


def migrate(database_url: str | None = None) -> tuple[list[str], dict[str, Any]]:
    """Apply all migrations to `database_url`; return (applied_files, summary)."""
    url = database_url or os.getenv("MIGRATE_DATABASE_URL") or DEFAULT_MIGRATE_URL
    files = sorted(MIGRATIONS_DIR.glob("*.sql"))
    if not files:
        raise RuntimeError("no migration files found under db/migrations")

    applied: list[str] = []
    conn = psycopg.connect(url, autocommit=False)
    try:
        for f in files:
            try:
                conn.execute(f.read_text(encoding="utf-8"))
            except Exception as exc:  # rollback, then surface with the file name
                conn.rollback()
                raise RuntimeError(f"migration {f.name} failed: {exc}") from exc
            conn.commit()
            applied.append(f.name)
        summary = verify(conn)
    finally:
        conn.close()
    return applied, summary


def verify(conn: Any) -> dict[str, Any]:
    """Assert the live schema matches the documented invariants; return summary."""
    with conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = sorted(row[0] for row in cur.fetchall())

        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
        indexes = sorted(row[0] for row in cur.fetchall())
        idx_named = [name for name in indexes if name.startswith("idx_")]

        cur.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c "
            "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"
        )
        rls = {row[0]: (row[1], row[2]) for row in cur.fetchall()}

        cur.execute(
            "SELECT c.relname FROM pg_policy p "
            "JOIN pg_class c ON c.oid = p.polrelid "
            "WHERE c.relnamespace = 'public'::regnamespace"
        )
        policy_tables = sorted(row[0] for row in cur.fetchall())

    enabled = {t for t, (e, _) in rls.items() if e}
    forced = {t for t, (_, f) in rls.items() if f}

    summary = {
        "tables": len(tables),
        "indexes": len(idx_named),
        "rls_enabled": len(enabled),
        "rls_forced": len(forced),
        "policies": len(policy_tables),
        "forced_tables": sorted(forced),
    }

    problems: list[str] = []
    if len(tables) != EXPECTED_TABLES:
        problems.append(f"tables: expected {EXPECTED_TABLES}, got {len(tables)}")
    if len(idx_named) != EXPECTED_IDX:
        problems.append(f"idx_ indexes: expected {EXPECTED_IDX}, got {len(idx_named)}")
    if len(enabled) != EXPECTED_RLS_TABLES or len(forced) != EXPECTED_RLS_TABLES:
        problems.append(
            f"rls enabled/forced: expected {EXPECTED_RLS_TABLES}/{EXPECTED_RLS_TABLES}, "
            f"got {len(enabled)}/{len(forced)}"
        )
    if len(policy_tables) != EXPECTED_POLICIES:
        problems.append(f"policies: expected {EXPECTED_POLICIES}, got {len(policy_tables)}")
    if "job_snapshots" not in tables:
        problems.append("job_snapshots table missing")
    if RLS_FREE_TABLE in enabled or RLS_FREE_TABLE in forced:
        problems.append(f"{RLS_FREE_TABLE} must stay RLS-exempt")

    if problems:
        raise AssertionError("schema invariants violated:\n  " + "\n  ".join(problems))
    return summary


def main() -> int:
    try:
        applied, summary = migrate()
    except Exception as exc:
        print(f"FAILED: {exc}", file=sys.stderr)
        return 1
    print(f"applied {len(applied)} migrations: {', '.join(applied)}")
    print(
        "verify: "
        + ", ".join(f"{k}={v}" for k, v in summary.items() if k != "forced_tables")
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())