"""T2 — data-access layer + RLS cross-user isolation matrix (S2).

Proves per-table, per-user isolation on all 19 RLS-covered tables, the shared
snapshot read (I1/I4), transaction rollback, and concurrency-safe snapshot writes.

All RLS-subject work connects as the ``app_user`` role (never the superuser). The
connection comes from ``DATABASE_URL`` (app_user), which under ``tasks.ps1 -Target
test-integration`` is loaded from ``.env.test`` and therefore points at the isolated
``:5435`` test cluster (see ``docs/testing-environment.md``).
"""

from __future__ import annotations

import asyncio
import os
import uuid

import psycopg
import pytest
from pytest_asyncio import fixture as async_fixture

from backend.app.db.context import DbContext
from backend.app.db.repositories import (
    AuthRepository,
    CoreEngineRepository,
    LlmRouterRepository,
)

APP_URL = os.getenv(
    "DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5432/autoapply"
)


async def _connect() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(APP_URL)


@async_fixture(scope="module")
async def world() -> dict:
    """Create users A and B plus the A-owned parent rows FK-bound tables need."""
    a, b = uuid.uuid4(), uuid.uuid4()

    async def create_user(uid: uuid.UUID) -> None:
        conn = await _connect()
        try:
            db = DbContext(conn, uid)
            repo = AuthRepository(db)
            async with db.transaction():
                await repo.insert(
                    "users",
                    {"id": uid, "email": f"{uid}@example.com", "password_hash": "x", "name": "User"},
                )
        finally:
            await conn.close()

    await asyncio.gather(create_user(a), create_user(b))

    # A-owned parent rows for FK-bound tables (profiles/jobs/llm_providers/applications).
    conn = await _connect()
    parents: dict[str, uuid.UUID] = {}
    try:
        db = DbContext(conn, a)
        core = CoreEngineRepository(db)
        llm = LlmRouterRepository(db)
        async with db.transaction():
            parents["profile"] = await core.insert(
                "profiles", {"user_id": a, "original_pdf_url": "resume-a.pdf", "json_resume": {"name": "A"}}
            )
            parents["job"] = await core.insert(
                "jobs",
                {"user_id": a, "title": "Engineer", "company": "Acme", "url": f"url-{a}",
                 "platform": "greenhouse", "source": "manual"},
            )
            parents["llm_provider"] = await llm.insert(
                "llm_providers", {"user_id": a, "name": "gemini", "base_url": "https://x", "model": "m"}
            )
            parents["application"] = await core.insert(
                "applications",
                {"user_id": a, "job_id": parents["job"], "profile_id": parents["profile"],
                 "optimized_resume": {"o": 1}, "pdf_url": "app-a.pdf", "field_mappings": {"f": 1}},
            )
    finally:
        await conn.close()

    return {"a": a, "b": b, "parents": parents}


# Per-table insert: (scoping column, columns). The scoping column is set to the active
# user inside each test. FKs reference the A-owned parent rows from the world fixture.
#   users -> scoped on `id` (no user_id column); everything else scopes on user_id.
TABLE_INSERTS: dict[str, tuple[str, list[str]]] = {
    "users": ("id", []),  # handled specially (see test)
    "profiles": ("user_id", ["original_pdf_url", "json_resume"]),
    "jobs": ("user_id", ["title", "company", "url", "platform", "source"]),
    "applications": ("user_id", ["job_id", "profile_id", "optimized_resume", "pdf_url", "field_mappings"]),
    "checkpoints": ("user_id", ["job_id", "step"]),
    "pipeline_runs": ("user_id", ["job_id", "trigger"]),
    "llm_providers": ("user_id", ["name", "base_url", "model"]),
    "provider_usage": ("user_id", ["provider_id", "latency_ms", "success"]),
    "rate_limit_state": ("user_id", ["provider_name"]),
    "telegram_connections": ("user_id", ["bot_token", "bot_username"]),
    "telegram_messages": ("user_id", ["chat_id", "message_id"]),
    "discord_connections": ("user_id", ["bot_token", "bot_username"]),
    "discord_messages": ("user_id", ["channel_id", "message_id", "author_id", "direction"]),
    "api_keys": ("user_id", ["key_hash", "name", "prefix"]),
    "audit_logs": ("user_id", ["action", "resource_type"]),
    "error_logs": ("user_id", ["component", "error_type", "severity", "message"]),
    "settings": ("user_id", ["key", "value"]),
    "user_profiles": ("user_id", ["phone"]),
    "job_snapshots": ("__exempt__", ["content_hash", "payload"]),  # shared, no scoping
}

_DEFAULT_SCOPED_COLUMNS: dict[str, dict[str, object]] = {
    "profiles": {"original_pdf_url": "r.pdf", "json_resume": {"n": 1}},
    "jobs": {"title": "Job", "company": "Co", "url": "", "platform": "greenhouse", "source": "manual"},
    "applications": {"optimized_resume": {"o": 1}, "pdf_url": "a.pdf", "field_mappings": {"f": 1}},
    "checkpoints": {"step": "scoring"},
    "pipeline_runs": {"trigger": "manual"},
    "llm_providers": {"name": "groq", "base_url": "b", "model": "m"},
    "provider_usage": {"latency_ms": 1, "success": True},
    "rate_limit_state": {"provider_name": "gemini"},
    "telegram_connections": {"bot_token": "t", "bot_username": "u"},
    "telegram_messages": {"chat_id": 1, "message_id": 1},
    "discord_connections": {"bot_token": "t", "bot_username": "u"},
    "discord_messages": {"channel_id": 1, "message_id": 1, "author_id": 1, "direction": "inbound"},
    "api_keys": {"key_hash": "k", "name": "n", "prefix": "p"},
    "audit_logs": {"action": "test", "resource_type": "test"},
    "error_logs": {"component": "c", "error_type": "e", "severity": "LOW", "message": "m"},
    "settings": {"key": "k", "value": {}},
    "user_profiles": {"phone": "1"},
}


def _repo(db: DbContext, table: str):
    """Pick the owning repository for a table, mirroring OWNERSHIP."""
    from backend.app.db.repositories import (
        OWNERSHIP,
        AuthRepository,
        CheckpointingRepository,
        ChromeExtensionRepository,
        CoreEngineRepository,
        DiscordRepository,
        DiscoveryRepository,
        LlmRouterRepository,
        ObservabilityRepository,
    )
    cls = {
        "AuthRepository": AuthRepository,
        "CheckpointingRepository": CheckpointingRepository,
        "ChromeExtensionRepository": ChromeExtensionRepository,
        "CoreEngineRepository": CoreEngineRepository,
        "DiscordRepository": DiscordRepository,
        "DiscoveryRepository": DiscoveryRepository,
        "LlmRouterRepository": LlmRouterRepository,
        "ObservabilityRepository": ObservabilityRepository,
    }[OWNERSHIP[table]]
    return cls(db)


async def _insert_owned(table: str, owner_uid: uuid.UUID, parents: dict) -> uuid.UUID:
    conn = await _connect()
    try:
        db = DbContext(conn, owner_uid)
        repo = _repo(db, table)
        scoping, _ = TABLE_INSERTS[table]
        cols: dict = dict(_DEFAULT_SCOPED_COLUMNS.get(table, {}))

        # Wire FK parents from the world fixture.
        if table == "applications":
            cols.update({"job_id": parents["job"], "profile_id": parents["profile"]})
        elif table in ("checkpoints", "pipeline_runs"):
            cols["job_id"] = parents["job"]
        elif table == "provider_usage":
            cols["provider_id"] = parents["llm_provider"]

        if scoping == "user_id":
            cols = {"user_id": owner_uid, **cols}
        elif scoping == "id":  # users
            cols = {"id": owner_uid, "email": f"{owner_uid}@example.com", "password_hash": "x", "name": "U"}
        # job_snapshots (__exempt__) has no scoping column.

        # settings has a composite PK (user_id, key) and no `id` column, so nothing to return.
        returning = None if table == "settings" else "id"
        async with db.transaction():
            return await repo.insert(table, cols, returning=returning)
    finally:
        await conn.close()


@pytest.mark.parametrize("table", sorted(TABLE_INSERTS.keys()))
async def test_rls_cross_user_isolation(table: str, world: dict) -> None:
    a, b, parents = world["a"], world["b"], world["parents"]

    if table == "users":
        # users scopes on `id`: each user sees exactly their own row (A and B both exist).
        conn = await _connect()
        try:
            for uid in (a, b):
                db = DbContext(conn, uid)
                repo = AuthRepository(db)
                async with db.transaction():
                    assert await repo.count("users") == 1
                    assert await repo.exists("users", "id", uid) is True
                    other = b if uid == a else a
                    assert await repo.exists("users", "id", other) is False
        finally:
            await conn.close()
        return

    if table == "job_snapshots":
        # RLS-exempt (I1): a snapshot written without any RLS scoping is readable by B.
        conn = await _connect()
        try:
            db = DbContext(conn, None)
            core = CoreEngineRepository(db)
            async with db.transaction():
                sid = await core.upsert_snapshot("shared-hash", {"title": "Shared"})
            # B reads it back (no RLS gate).
            db_b = DbContext(conn, b)
            async with db_b.transaction():
                got = await core.exists("job_snapshots", "id", sid)
            assert got is True
        finally:
            await conn.close()
        return

    # Policy tables: A inserts an A-owned row; B sees none of it.
    rid = await _insert_owned(table, a, parents)

    conn = await _connect()
    try:
        db_a = DbContext(conn, a)
        db_b = DbContext(conn, b)
        a_count, b_count = 0, 0
        async with db_a.transaction():
            a_count = await _repo(db_a, table).count(table)
        async with db_b.transaction():
            b_count = await _repo(db_b, table).count(table)
            b_sees = await _repo(db_b, table).exists(table, "id", rid) if rid else False
        assert a_count >= 1, f"user A should see its own {table} row"
        assert b_count == 0, f"user B leaked {b_count} row(s) of {table}"
        if rid is not None:
            assert b_sees is False, f"user B could read A's {table} row directly"
    finally:
        await conn.close()


async def test_default_denied_without_identity(world: dict) -> None:
    """D5: a missing identity is FAIL-CLOSED, never a silent grant.

    - Bare app_user connection, no SET LOCAL: ``app.user_id`` was never registered this
      session, so ``current_setting('app.user_id')`` (no missing_ok) inside the RLS policy
      raises UndefinedObject -> the whole query fails. No NULL compare, no leaked rows.
    - DbContext(None) sets the GUC to NULL explicitly -> ``user_id = NULL::uuid`` matches
      nothing -> default-denied (0 rows), the documented safe path.
    """
    conn = await _connect()
    conn_dn = await _connect()
    try:
        # (1) policy-table read on a bare connection errors (fail-closed).
        with pytest.raises(psycopg.errors.UndefinedObject):
            await conn.execute("SELECT count(*) FROM settings")
        # (2) explicit NULL identity -> default-denied (0 rows) via the zero-UUID sentinel.
        #     Fresh connection: the UndefinedObject above aborted the first connection.
        db = DbContext(conn_dn, None)
        async with db.transaction():
            n = await db.fetch_scalar("SELECT count(*) FROM settings")
        assert int(n or 0) == 0
    finally:
        await conn.close()
        await conn_dn.close()


async def test_snapshot_shared_read_exempt(world: dict) -> None:
    """I1/I4: a shared snapshot written by A is readable by B (RLS-exempt, no user_id)."""
    a, b = world["a"], world["b"]
    conn_a = await _connect()
    conn_b = await _connect()
    try:
        core = CoreEngineRepository(DbContext(conn_a, a))
        async with core.db.transaction():
            sid = await core.upsert_snapshot("shared-i1", {"title": "X"})
        core_b = CoreEngineRepository(DbContext(conn_b, b))
        async with core_b.db.transaction():
            assert await core_b.exists("job_snapshots", "id", sid) is True
    finally:
        await conn_a.close()
        await conn_b.close()


async def test_context_transaction_rollback(world: dict) -> None:
    """Two statements in one DbContext; the second fails -> both rolled back."""
    a = world["a"]
    conn = await _connect()
    try:
        db = DbContext(conn, a)
        core = CoreEngineRepository(db)
        with pytest.raises(psycopg.errors.CheckViolation):
            async with db.transaction():
                await core.insert(
                    "jobs",
                    {"user_id": a, "title": "Bad", "company": "Co", "url": "bad-url",
                     "platform": "greenhouse", "source": "manual"},
                )
                # Violates platform CHECK -> whole transaction rolls back (S2 rollback semantics).
                await core.insert(
                    "jobs",
                    {"user_id": a, "title": "Bad", "company": "Co", "url": "bad-url-2",
                     "platform": "not-a-platform", "source": "manual"},
                )
        async with db.transaction():
            # Neither row survived the aborted transaction (RLS-scoped, URL-specific proof).
            assert await core.exists("jobs", "url", "bad-url") is False
            assert await core.exists("jobs", "url", "bad-url-2") is False
    finally:
        await conn.close()


async def test_concurrent_same_snapshot(world: dict) -> None:
    """I4: N concurrent upserts of the same content_hash yield exactly one row, no PK violation."""
    n = 8
    user_ids = [uuid.uuid4() for _ in range(n)]

    async def one(uid: uuid.UUID) -> uuid.UUID:
        conn = await _connect()
        try:
            core = CoreEngineRepository(DbContext(conn, uid))
            async with core.db.transaction():
                return await core.upsert_snapshot("race-hash", {"i": 1})
        finally:
            await conn.close()

    ids = await asyncio.gather(*(one(u) for u in user_ids))
    assert len(set(uuid.UUID(str(x)) for x in ids)) == 1, "all writers must converge on one snapshot id"

    conn = await _connect()
    try:
        async with DbContext(conn, None).transaction() as db:
            n_rows = await db.fetch_scalar(
                "SELECT count(*) FROM job_snapshots WHERE content_hash = %s", ("race-hash",)
            )
        assert int(n_rows or 0) == 1
    finally:
        await conn.close()
