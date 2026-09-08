"""PCB-per-run ephemeral test databases (enterprise pattern).

The test stack's persistent ``autoapply`` database is the **baseline**: migrated once
by ``test-env-up`` and never touched by tests. Every test run clones it via
``CREATE DATABASE <clone> TEMPLATE autoapply`` (copy-on-write), runs the suite against
that disposable clone, then drops it — keeping the most recent clone alive for post-run
inspection in pgAdmin.

This decouples the *schema* lifecycle (deterministic, baseline) from the *data* lifecycle
(ephemeral, per-run) without ever wiping the persistent stack.

Connection: ``MIGRATE_DATABASE_URL`` env var (the ``autoapply`` cluster superuser on the
test stack, default dev). DATABASE/table helpers shell out to psycopg.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import psycopg.errors

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from db.run_migrations import migrate  # noqa: E402

BASE_DB = "autoapply"
PREFIX = "app_test"
KEEP_LAST = 1  # keep the most recent N ephemeral DBs for inspection


# --------------------------------------------------------------------------- #
# URL helpers
# --------------------------------------------------------------------------- #
def admin_url() -> str:
    """Admin URL for cluster ops, connected to the maintenance ``postgres`` DB.

    Creating a database with ``TEMPLATE autoapply`` requires no active sessions on
    ``autoapply``; connecting to ``postgres`` (not the template) avoids self-locking.
    """
    url = os.getenv("MIGRATE_DATABASE_URL", "postgresql://autoapply:autoapply@localhost:5432/autoapply")
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))


def db_url(dbname: str) -> str:
    """Point the admin URL at a specific database (same creds, new path)."""
    url = admin_url()
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, f"/{dbname}", parts.query, parts.fragment))


# --------------------------------------------------------------------------- #
# Baseline
# --------------------------------------------------------------------------- #
def is_migrated(dbname: str = BASE_DB) -> bool:
    """True if the schema is applied (marker: `public.users` exists)."""
    with psycopg.connect(db_url(dbname)) as conn:
        row = conn.execute("SELECT to_regclass('public.users')").fetchone()
    return row[0] is not None


def ensure_baseline() -> None:
    """Migrate the baseline DB if it is not already migrated (idempotent)."""
    if not is_migrated():
        migrate(db_url(BASE_DB))


# --------------------------------------------------------------------------- #
# Ephemeral DB lifecycle
# --------------------------------------------------------------------------- #
def existing_clones() -> list[str]:
    with psycopg.connect(admin_url()) as conn:
        rows = conn.execute(
            "SELECT datname FROM pg_database WHERE datname LIKE %s ORDER BY datname",
            (f"{PREFIX}_%",),
        ).fetchall()
    return [r[0] for r in rows]


def create_clone() -> str:
    """Create a uniquely-named clone of the baseline; returns its DB name."""
    import datetime

    name = f"{PREFIX}_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}"
    with psycopg.connect(admin_url(), autocommit=True) as conn:
        conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        conn.execute(f"CREATE DATABASE {name} TEMPLATE {BASE_DB}")
    return name


def cleanup(keep: int = KEEP_LAST) -> list[str]:
    """Drop all stochastic clones except the ``keep`` most recent; return dropped names."""
    clones = existing_clones()
    # 'app_test_YYYYMMDDHHMMSS' sorts lexically by time, newest last; keep the tail.
    drop = clones[:-keep] if keep > 0 else clones
    dropped: list[str] = []
    with psycopg.connect(admin_url(), autocommit=True) as conn:
        for name in drop:
            conn.execute(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
            dropped.append(name)
    return dropped


def main() -> int:
    import sys

    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    try:
        if cmd == "create":
            print(create_clone())
        elif cmd == "cleanup":
            dropped = cleanup()
            print(f"dropped {len(dropped)} clone(s): {', '.join(dropped) or '(none)'}")
        elif cmd == "ensure-baseline":
            ensure_baseline()
            print(f"baseline '{BASE_DB}' ready")
        elif cmd == "list":
            clones = existing_clones()
            print(f"clones ({len(clones)}): {', '.join(clones) or '(none)'}")
        else:
            raise SystemExit(f"usage: {sys.argv[0]} <create|cleanup|ensure-baseline|list>")
    except Exception as exc:  # surface to caller, non-zero exit
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
