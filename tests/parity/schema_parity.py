"""Schema parity harness (S1).

Two layers of drift protection against docs/database/schema.md:

1. **Golden pg_dump diff** - dumps the live schema and diffs it against the
   committed golden dump (tests/parity/golden/schema_golden.sql) so no schema
   object can silently change or disappear.

2. **Docs inventory matcher** - parses the docs' DDL text (tables / idx_*
   indexes / policies / ENABLE+FORCE RLS) and compares it with the live
   PostgreSQL catalogs, with the S1 doc divergences (D1..D4) encoded so a
   divergence is always explicit, never silent.

Usage (db container must be running with migrations applied):
    python tests/parity/schema_parity.py

The golden pg_dump runs inside the target DB container. Which stack is dumped is
selected by env (default = dev):
    PARITY_COMPOSE      e.g. infra/docker-compose.test.yml  (default dev.yml)
    PARITY_DB_SERVICE   e.g. db_test                        (default db)
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import psycopg

REPO = Path(__file__).resolve().parents[2]
DOCS_SCHEMA = REPO / "docs" / "database" / "schema.md"
GOLDEN = REPO / "tests" / "parity" / "golden" / "schema_golden.sql"
COMPOSE = REPO / os.getenv("PARITY_COMPOSE", "infra/docker-compose.dev.yml")
DB_SERVICE = os.getenv("PARITY_DB_SERVICE", "db")

DEFAULT_MIGRATE_URL = "postgresql://autoapply:autoapply@localhost:5435/autoapply"

# S1 documented divergences (reconciled in the migrations, final-schema-preserving):
#   D1: doc 007's discord ENABLE+policy block moved to 022 (tables created there).
#   D2: doc 023's user_profiles FORCE line moved to 024 (table created there).
#   D3: CREATE ROLE wrapped in an idempotent guard (roles are cluster-wide).
#   D4: doc FORCEs RLS on user_profiles but never ENABLEs it nor defines a policy;
#       024 therefore adds ENABLE + FORCE + user_isolation policy.
DIVERGENCE_D4_EXTRA_POLICIES = {"user_profiles": {"user_isolation"}}
RLS_EXEMPT = {"job_snapshots"}
EXPECTED_POLICY_COUNT = 22  # 20 documented + D4 user_profiles + 026 auth_sessions

_RE_TABLE = re.compile(r"^CREATE TABLE (?:IF NOT EXISTS )?(\w+)\s*\(", re.M)
_RE_IDX = re.compile(r"^CREATE (?:UNIQUE )?INDEX (idx_\w+)\b", re.M)
_RE_POLICY = re.compile(r"^CREATE POLICY (\w+)\b", re.M)
_RE_ENABLE = re.compile(r"^ALTER TABLE (\w+) ENABLE ROW LEVEL SECURITY", re.M)
_RE_FORCE = re.compile(r"^ALTER TABLE (\w+) FORCE ROW LEVEL SECURITY", re.M)


# --------------------------------------------------------------------------- #
# Layer 1: golden pg_dump diff
# --------------------------------------------------------------------------- #
def dump_schema() -> str:
    """pg_dump the live schema (schema-only, no owner/privileges) via the db container."""
    result = subprocess.run(
        [
            "docker",
            "compose",
            "-f",
            str(COMPOSE),
            "exec",
            "-T",
            DB_SERVICE,
            "pg_dump",
            "-U",
            "autoapply",
            "--schema-only",
            "--no-owner",
            "--no-privileges",
            "autoapply",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"pg_dump failed:\n{result.stderr}")
    return result.stdout


def normalize_dump(dump: str) -> str:
    """Drop the volatile comment/SET lines so only schema objects are compared."""
    kept: list[str] = []
    for line in dump.splitlines():
        line = line.rstrip()
        if not line:
            continue
        if line.startswith("--"):
            continue
        if line.startswith("SET "):
            continue
        if line.startswith("\\restrict") or line.startswith("\\unrestrict"):
            continue  # per-dump random nonce pair (pg_dump >= 16.x)
        kept.append(line)
    return "\n".join(kept) + "\n"


def golden_check() -> dict[str, Any]:
    """Compare live dump to the committed golden dump. Empty diff means success."""
    if not GOLDEN.is_file():
        return {"ok": False, "error": f"golden dump missing: {GOLDEN}"}
    live = normalize_dump(dump_schema())
    golden = normalize_dump(GOLDEN.read_text(encoding="utf-8"))
    if live == golden:
        return {"ok": True, "error": None}
    live_lines = live.splitlines()
    golden_lines = golden.splitlines()
    for i, (a, b) in enumerate(zip(live_lines, golden_lines, strict=False)):
        if a != b:
            return {
                "ok": False,
                "error": f"first diff at line {i + 1}\n  golden: {b}\n  live:  {a}",
            }
    return {"ok": False, "error": f"line counts differ (golden={len(golden_lines)}, live={len(live_lines)})"}


# --------------------------------------------------------------------------- #
# Layer 2: docs inventory matcher
# --------------------------------------------------------------------------- #
def docs_inventory() -> dict[str, Any]:
    text = DOCS_SCHEMA.read_text(encoding="utf-8")
    tables = set(_RE_TABLE.findall(text))
    indexes = set(_RE_IDX.findall(text))
    policies = set(_RE_POLICY.findall(text))
    enables = set(_RE_ENABLE.findall(text))
    forces = set(_RE_FORCE.findall(text))
    return {
        "tables": tables,
        "indexes": indexes,
        "policies": policies,
        "enables": enables,
        "forces": forces,
    }


def live_catalog(url: str | None = None) -> dict[str, Any]:
    url = url or os.getenv("MIGRATE_DATABASE_URL") or DEFAULT_MIGRATE_URL
    with psycopg.connect(url) as conn, conn.cursor() as cur:
        cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        tables = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE 'idx\\_%'")
        indexes = {row[0] for row in cur.fetchall()}
        cur.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c "
            "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"
        )
        rls_rows = cur.fetchall()
        enabled = {row[0] for row in rls_rows if row[1]}
        forced = {row[0] for row in rls_rows if row[2]}
        cur.execute(
            "SELECT c.relname FROM pg_policy p "
            "JOIN pg_class c ON c.oid = p.polrelid "
            "WHERE c.relnamespace = 'public'::regnamespace"
        )
        policy_tables = {row[0] for row in cur.fetchall()}
        cur.execute(
            "SELECT count(*) FROM pg_policy p "
            "JOIN pg_class c ON c.oid = p.polrelid "
            "WHERE c.relnamespace = 'public'::regnamespace"
        )
        policy_count = cur.fetchone()[0]
    return {
        "tables": tables,
        "indexes": indexes,
        "enables": enabled,
        "forces": forced,
        "policy_tables": policy_tables,
        "policy_count": policy_count,
    }


def docs_matcher(url: str | None = None) -> dict[str, Any]:
    """Compare docs inventory with live catalogs; doc divergences encoded."""
    doc = docs_inventory()
    live = live_catalog(url)

    errors: list[str] = []

    if live["tables"] != doc["tables"]:
        errors.append(f"tables: docs={sorted(doc['tables'])} live={sorted(live['tables'])}")
    if live["indexes"] != doc["indexes"]:
        errors.append(f"idx_ indexes: docs={sorted(doc['indexes'])} live={sorted(live['indexes'])}")

    expected_enabled = (doc["enables"] | set(DIVERGENCE_D4_EXTRA_POLICIES)) - RLS_EXEMPT
    if live["enables"] != expected_enabled:
        errors.append(f"RLS enabled: docs+{sorted(expected_enabled)} live={sorted(live['enables'])}")
    if live["forces"] != doc["forces"]:
        errors.append(f"RLS forced: docs={sorted(doc['forces'])} live={sorted(live['forces'])}")
    if live["policy_tables"] != expected_enabled:
        errors.append(
            f"policy-carrying tables != RLS tables: "
            f"policies={sorted(live['policy_tables'])} enabled={sorted(live['enables'])}"
        )
    if live["policy_count"] != EXPECTED_POLICY_COUNT:
        errors.append(
            f"policy count: expected {EXPECTED_POLICY_COUNT}, "
            f"got {live['policy_count']} (20 doc statements + D4 user_profiles + 026)"
        )
    if RLS_EXEMPT & (live["enables"] | live["forces"]):
        errors.append(f"{RLS_EXEMPT} must stay RLS-exempt")

    return {"ok": not errors, "errors": errors}


# --------------------------------------------------------------------------- #
def compare(url: str | None = None) -> dict[str, Any]:
    golden = golden_check()
    matcher = docs_matcher(url)
    problems = []
    if not golden["ok"]:
        problems.append(f"golden diff: {golden['error']}")
    problems.extend(matcher["errors"])
    return {"ok": not problems, "problems": problems, "golden": golden, "matcher": matcher}


def main() -> int:
    result = compare()
    report_lines = [
        "schema parity: " + ("PASS" if result["ok"] else "FAIL"),
    ]
    if result["ok"]:
        print("\n".join(report_lines))
        print("  golden pg_dump diff   : clean (tables/indexes/fks match committed golden)")
        print("  docs matcher          : docs/database/schema.md matches live catalogs")
        print("  policy-carry tables   : == RLS-enabled tables (20), job_snapshots exempt")
        return 0
    report_lines.append(f"  golden diff: {result['golden']['error']}")
    for err in result["problems"]:
        report_lines.append("  " + err)
    print("\n".join(report_lines), file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
