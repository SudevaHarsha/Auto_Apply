"""T1 integration tests: migrations create the documented schema (S1)."""

import os
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from db.run_migrations import (
    migrate,
    verify,
)
from tests.parity import schema_parity

ADMIN_URL = os.getenv("MIGRATE_DATABASE_URL", "postgresql://autoapply:autoapply@localhost:5432/autoapply")
SCRATCH_DB = "autoapply_ci_scratch"


def _maintenance_url() -> str:
    """Same admin credentials, connected to the cluster 'postgres' db."""
    parts = urlsplit(ADMIN_URL)
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", parts.query, parts.fragment))


@pytest.fixture(scope="module")
def summary() -> dict:
    with psycopg.connect(ADMIN_URL) as conn:
        return verify(conn)


def test_migration_apply_and_verify(summary: dict) -> None:
    assert summary["tables"] == 21  # +026 auth_sessions
    assert summary["indexes"] == 39  # +2 idx_auth_sessions_*
    assert summary["rls_enabled"] == 20
    assert summary["rls_forced"] == 20
    assert summary["policies"] == 22


def test_app_user_role_exists() -> None:
    with psycopg.connect(ADMIN_URL) as conn:
        row = conn.execute("SELECT 1 FROM pg_roles WHERE rolname = 'app_user'").fetchone()
    assert row is not None, "app_user role missing (D3 idempotent guard failed?)"


def test_migrations_apply_twice_on_fresh_db() -> None:
    admin = psycopg.connect(_maintenance_url(), autocommit=True)
    scratch_url = ADMIN_URL.rsplit("/", 1)[0] + "/" + SCRATCH_DB
    try:
        for _ in range(2):
            admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
            admin.execute(f"CREATE DATABASE {SCRATCH_DB}")
            applied, summary = migrate(scratch_url)
            assert len(applied) == 27  # 001..027
            assert summary["tables"] == 21
            assert summary["policies"] == 22
    finally:
        admin.execute(f"DROP DATABASE IF EXISTS {SCRATCH_DB} WITH (FORCE)")
        admin.close()


def test_rls_forced_19_and_snapshots_are_exempt() -> None:
    with psycopg.connect(ADMIN_URL) as conn:
        rows = conn.execute(
            "SELECT c.relname, c.relrowsecurity, c.relforcerowsecurity "
            "FROM pg_class c "
            "WHERE c.relnamespace = 'public'::regnamespace AND c.relkind = 'r'"
        ).fetchall()
    rls = {name: (en, fo) for name, en, fo in rows}
    enabled = {t for t, (e, _) in rls.items() if e}
    forced = {t for t, (_, f) in rls.items() if f}
    assert len(enabled) == 20
    assert len(forced) == 20
    assert "user_profiles" in forced  # D4/D2: FORCE + policy present
    assert "auth_sessions" in forced  # 026: same tenant-scope contract
    assert "job_snapshots" not in enabled
    assert "job_snapshots" not in forced


def test_job_snapshots_columns_and_unique_hash() -> None:
    with psycopg.connect(ADMIN_URL) as conn:
        cols = {
            row[0]
            for row in conn.execute(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = 'job_snapshots'"
            ).fetchall()
        }
        unique = conn.execute(
            "SELECT count(*) FROM pg_constraint WHERE conrelid = 'job_snapshots'::regclass AND contype = 'u'"
        ).fetchone()[0]
    assert cols == {"id", "content_hash", "payload", "captured_at"}
    assert "user_id" not in cols  # shared cache invariant: no owner column
    assert unique == 1  # UNIQUE(content_hash)


def test_skip_reason_is_applications_only() -> None:
    def columns(table: str) -> set[str]:
        with psycopg.connect(ADMIN_URL) as conn:
            return {
                row[0]
                for row in conn.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = %s",
                    (table,),
                ).fetchall()
            }

    assert "skip_reason" in columns("applications")
    assert "skip_reason" not in columns("jobs")


def test_checkpoint_step_enum_is_exact() -> None:
    with psycopg.connect(ADMIN_URL) as conn:
        defs = conn.execute(
            "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
            "WHERE conrelid = 'checkpoints'::regclass AND contype = 'c'"
        ).fetchall()
    step_def = next(d[0] for d in defs if "'jd_extraction'" in d[0] and "'rubric_generation'" in d[0])
    expected = {"jd_extraction", "rubric_generation", "scoring", "optimization", "package_generation"}
    for value in expected:
        assert f"'{value}'" in step_def
    assert step_def.count("'") // 2 == len(expected), "unexpected extra step literals"


def test_index_count_39() -> None:
    with psycopg.connect(ADMIN_URL) as conn:
        count = conn.execute(
            "SELECT count(*) FROM pg_indexes WHERE schemaname = 'public' AND indexname LIKE 'idx\\_%'"
        ).fetchone()[0]
    assert count == 39


def test_snapshot_fks_on_applications_and_jobs() -> None:
    with psycopg.connect(ADMIN_URL) as conn:
        refs = {
            row[0]
            for row in conn.execute(
                "SELECT conname FROM pg_constraint WHERE confrelid = 'job_snapshots'::regclass"
            ).fetchall()
        }
        jobs_snapshot_col = conn.execute(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'jobs' "
            "AND column_name = 'current_snapshot_id'"
        ).fetchone()
    assert "fk_jobs_snapshot" in refs
    assert "applications_snapshot_id_fkey" in refs
    assert jobs_snapshot_col is not None


def test_golden_dump_diff_is_clean() -> None:
    result = schema_parity.golden_check()
    assert result["ok"], result["error"]


def test_docs_matcher_passes() -> None:
    assert schema_parity.DOCS_SCHEMA.is_file(), "docs/database/schema.md not found"
    result = schema_parity.docs_matcher(ADMIN_URL)
    assert result["ok"], "\n".join(result["errors"])
