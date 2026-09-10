"""T4 — LLM router through the service layer (S4): D13-D20 + B1/B2/B4 proofs.

Drives ``route_llm_request`` / ``generate_structured`` / ``LlmProviderService`` over
a live connection with the deterministic mock sequencer from ``tests/doubles``
(D14: the real adapters are unit-tested offline via ``httpx`` MockTransport; the mock
is physically unreachable from ``backend/app`` — guarded). Breaker timing is fully
deterministic: the clock is injected (D16), nothing sleeps.
"""

from __future__ import annotations

import asyncio
import json
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import psycopg
import pytest
from pydantic import BaseModel

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("LLM_PROVIDER_MASTER_KEY", "0123456789abcdef0123456789abcdef")

from backend.app.auth.errors import SettingsValueInvalidError
from backend.app.auth.service import AuthService
from backend.app.auth.settings_service import SettingsService
from backend.app.db.context import DbContext
from backend.app.db.repositories.llm_router_repository import LlmRouterRepository
from backend.app.llm.adapters.gemini import GeminiAdapter
from backend.app.llm.adapters.ollama import OllamaAdapter
from backend.app.llm.adapters.openai_compatible import OpenAICompatibleAdapter
from backend.app.llm.crypto import DecryptionError, decrypt_provider_key
from backend.app.llm.errors import (
    LLM_PROVIDERS_EXHAUSTED,
    ProviderDuplicateError,
    ProviderNotFoundError,
    ProvidersExhaustedError,
    ProviderTestFailedError,
    ValidationError,
)
from backend.app.llm.json_utils import parse_llm_json
from backend.app.llm.registry import is_registered, spec_for
from backend.app.llm.router import (
    COOLDOWN_FLOOR_SECONDS,
    cooldown_for_retry_after,
    generate_structured,
    route_llm_request,
)
from backend.app.llm.service import LlmProviderService
from backend.app.main import app
from tests.doubles.mock_provider import (
    http,
    invalid_key,
    ok,
    rate_limited,
    scripted_factory,
    timeout,
    unavailable,
)

os.environ.setdefault("LLM_PROVIDER_MASTER_KEY", "0123456789abcdef0123456789abcdef")

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5432/autoapply")

PASSWORD = "Str0ng!password"

DEFAULT_CHAIN = ["gemini", "ollama", "groq", "openrouter"]

PROVIDER_URLS = {"gemini": "https://generativelanguage.googleapis.com", "ollama": "http://localhost:11434"}


async def _conn() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(APP_URL)


def _mail(tag: str = "t") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.com"


async def _register() -> tuple[psycopg.AsyncConnection, dict]:
    conn = await _conn()
    try:
        result = await AuthService(conn).register(email=_mail(), password=PASSWORD, name="LLM Tester")
    except Exception:
        await conn.close()
        raise
    return conn, {"result": result}


async def _add_provider(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    name: str,
    *,
    api_key: str | None = None,
    priority: int = 0,
) -> None:
    await LlmProviderService(conn).add_provider(
        user_id=user_id,
        name=name,
        base_url=PROVIDER_URLS.get(name, f"http://{name}.example.com/v1"),
        model=f"{name}-model",
        api_key=api_key,
        priority=priority,
    )


async def _add_job(conn: psycopg.AsyncConnection, user_id: uuid.UUID) -> uuid.UUID:
    async with DbContext(conn, user_id).transaction() as db:
        return await db.fetch_scalar(
            "INSERT INTO jobs (user_id, title, company, url, platform, source) "
            "VALUES (%s, 'title', 'company', 'https://example.com/job', 'greenhouse', 'manual') RETURNING id",
            (str(user_id),),
        )


async def _breaker(conn: psycopg.AsyncConnection, user_id: uuid.UUID, name: str) -> dict | None:
    async with DbContext(conn, user_id).transaction() as db:
        return await LlmRouterRepository(db).get_breaker(user_id, name)


async def _count(conn: psycopg.AsyncConnection, user_id: uuid.UUID, query: str, *params: object) -> int:
    async with DbContext(conn, user_id).transaction() as db:
        n = await db.fetch_scalar(query, tuple(params))
    return int(n or 0)


def _assert_envelope_shape(exc: Exception) -> None:
    env = exc.envelope()["error"]
    assert env["code"] and env["timestamp"] and env["request_id"]


# =========================================================== 1/3d chain order + 429
async def test_chain_order_and_retry_after_failover() -> None:
    """Highest-priority provider forced 429 -> failover to next; Retry-After drives cooldown."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini", priority=0)
        await _add_provider(conn, uid, "ollama", priority=10)
        factory, _adapters, events = scripted_factory({"gemini": [rate_limited(13)], "ollama": [ok()]})
        now = datetime.now(UTC)
        result = await route_llm_request(conn, user_id=uid, prompt="hi", adapter_factory=factory, now=now)
        assert result.provider == "ollama"
        assert events == ["gemini", "ollama"]
        breaker = await _breaker(conn, uid, "gemini")
        assert breaker["state"] == "OPEN"
        assert breaker["failure_count"] == 0  # 429 never counts toward the trip counter
        assert breaker["cooldown_expires_at"] == cooldown_for_retry_after(13, "gemini", now)
        assert (
            await _count(conn, uid, "SELECT count(*) FROM provider_usage WHERE user_id = %s AND success = false", uid)
            == 1
        )
        assert (
            await _count(conn, uid, "SELECT count(*) FROM provider_usage WHERE user_id = %s AND success = true", uid)
            == 1
        )
    finally:
        await conn.close()


# ---------------------------------------------------------------------- D17
async def test_failover_all_failed_marker_and_per_provider_breakers() -> None:
    """All providers fail (mixed 429/500/timeout); exhaustion writes marker+audit+503."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini", priority=0)
        await _add_provider(conn, uid, "ollama", priority=10)
        await _add_provider(conn, uid, "groq", priority=20)
        job_id = await _add_job(conn, uid)
        factory, _adapters, events = scripted_factory(
            {"gemini": [rate_limited(30)], "ollama": [http(500)], "groq": [timeout()]}
        )
        now = datetime.now(UTC)
        with pytest.raises(ProvidersExhaustedError) as exc:
            await route_llm_request(
                conn, user_id=uid, prompt="hi", job_id=job_id, step="scoring", adapter_factory=factory, now=now
            )
        assert exc.value.status == 503
        assert exc.value.code == LLM_PROVIDERS_EXHAUSTED
        _assert_envelope_shape(exc.value)
        assert events == ["gemini", "ollama", "groq"]  # no provider retried

        async with DbContext(conn, uid).transaction() as db:
            marker_row = await (
                await db.execute("SELECT pipeline_state FROM checkpoints WHERE job_id = %s", (str(job_id),))
            ).fetchone()
        assert marker_row is not None
        marker = marker_row[0]
        assert marker["llm_all_providers_exhausted"] is True
        assert set(marker["failed_providers"]) == {"gemini", "ollama", "groq"}
        assert await _count(conn, uid, "SELECT count(*) FROM audit_logs WHERE action = 'all_providers_exhausted'") == 1
        assert await _count(conn, uid, "SELECT count(*) FROM audit_logs WHERE action = 'llm_provider_failed'") == 3

        g = await _breaker(conn, uid, "gemini")
        assert g["state"] == "OPEN" and g["failure_count"] == 0
        assert g["cooldown_expires_at"] == cooldown_for_retry_after(30, "gemini", now)
        o = await _breaker(conn, uid, "ollama")
        assert o["state"] == "CLOSED" and o["failure_count"] == 1
        r = await _breaker(conn, uid, "groq")
        assert r["state"] == "CLOSED" and r["failure_count"] == 1
    finally:
        await conn.close()


async def test_exhaustion_audit_only_no_job_context() -> None:
    """Without job+step: checkpoint count stays 0; audit + 503 still emitted (D17 branch 2)."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini")
        factory, _adapters, _events = scripted_factory({"gemini": [http(500)]})
        with pytest.raises(ProvidersExhaustedError) as exc:
            await route_llm_request(conn, user_id=uid, prompt="hi", adapter_factory=factory)
        assert exc.value.status == 503
        assert exc.value.code == LLM_PROVIDERS_EXHAUSTED
        assert await _count(conn, uid, "SELECT count(*) FROM checkpoints WHERE user_id = %s", uid) == 0
        assert await _count(conn, uid, "SELECT count(*) FROM audit_logs WHERE action = 'all_providers_exhausted'") == 1
    finally:
        await conn.close()


# --------------------------------------------------------------- circuit breaker
async def test_circuit_breaker_lifecycle_no_sleeps() -> None:
    """N failures trip OPEN; OPEN skips during cooldown; HALF_OPEN admits one trial; success resets."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini")
        factory, adapters, _events = scripted_factory({"gemini": [http(500), http(500), http(500)]})
        now = datetime.now(UTC)
        for _ in range(3):  # each failure exhausts the single-provider chain
            with pytest.raises(ProvidersExhaustedError):
                await route_llm_request(conn, user_id=uid, prompt="hi", adapter_factory=factory, now=now)
        breaker = await _breaker(conn, uid, "gemini")
        assert breaker["state"] == "OPEN" and breaker["failure_count"] == 3
        assert breaker["cooldown_expires_at"] == now + timedelta(seconds=COOLDOWN_FLOOR_SECONDS)

        # OPEN + in cooldown -> skipped, no provider call -> exhaustion
        with pytest.raises(ProvidersExhaustedError):
            await route_llm_request(
                conn, user_id=uid, prompt="hi", adapter_factory=factory, now=now + timedelta(seconds=5)
            )
        assert len(adapters["gemini"].calls) == 3

        # cooldown expired -> single HALF_OPEN trial -> success resets to CLOSED
        result = await route_llm_request(
            conn, user_id=uid, prompt="hi", adapter_factory=factory, now=now + timedelta(seconds=40)
        )
        assert result.provider == "gemini"
        assert len(adapters["gemini"].calls) == 4
        breaker = await _breaker(conn, uid, "gemini")
        assert breaker["state"] == "CLOSED" and breaker["failure_count"] == 0
        assert breaker["cooldown_expires_at"] is None
    finally:
        await conn.close()


async def test_breaker_claim_and_failure_increment_are_atomic() -> None:
    """Two concurrent peers: exactly one HALF_OPEN trial claim and one failure increment (D16)."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        now = datetime.now(UTC)
        async with DbContext(conn, uid).transaction() as db:
            repo = LlmRouterRepository(db)
            await repo.ensure_breaker(uid, "gemini")
            await db.execute(
                "UPDATE rate_limit_state SET state = 'OPEN', cooldown_expires_at = %s WHERE provider_name = 'gemini'",
                (now - timedelta(minutes=5),),
            )
        conn2 = await _conn()
        try:

            async def claim_peer(c: psycopg.AsyncConnection) -> bool:
                async with DbContext(c, uid).transaction() as db:
                    return await LlmRouterRepository(db).claim_trial(uid, "gemini", now=now)

            results = await asyncio.gather(claim_peer(conn), claim_peer(conn2))
            assert sorted(results) == [False, True]

            async def inc_peer(c: psycopg.AsyncConnection) -> bool:
                async with DbContext(c, uid).transaction() as db:
                    return await LlmRouterRepository(db).increment_failure(
                        uid, "gemini", current_failure_count=0, last_failure_at=now
                    )

            async with DbContext(conn, uid).transaction() as db:
                await db.execute(
                    "UPDATE rate_limit_state SET state = 'CLOSED', failure_count = 0 WHERE provider_name = 'gemini'"
                )
            results = await asyncio.gather(inc_peer(conn), inc_peer(conn2))
            assert sorted(results) == [False, True]
            breaker = await _breaker(conn, uid, "gemini")
            assert breaker["failure_count"] == 1
        finally:
            await conn2.close()
    finally:
        await conn.close()


async def test_retry_after_drives_cooldown() -> None:
    """cooldown = now + max(floor, Retry-After ±20%); headerless 429 uses the floor (D16)."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        now = datetime.now(UTC)

        await _add_provider(conn, uid, "gemini", priority=0)
        await _add_provider(conn, uid, "ollama", priority=1)
        await _add_provider(conn, uid, "groq", priority=2)

        big_factory, _a, _e = scripted_factory({"gemini": [rate_limited(120)]})
        with pytest.raises(ProvidersExhaustedError):
            await route_llm_request(
                conn, user_id=uid, prompt="x", provider_chain=["gemini"], adapter_factory=big_factory, now=now
            )
        breaker = await _breaker(conn, uid, "gemini")
        assert breaker["state"] == "OPEN" and breaker["failure_count"] == 0
        assert breaker["cooldown_expires_at"] == cooldown_for_retry_after(120, "gemini", now)

        floor_factory, _a, _e = scripted_factory({"ollama": [rate_limited(None)]})
        with pytest.raises(ProvidersExhaustedError):
            await route_llm_request(
                conn, user_id=uid, prompt="x", provider_chain=["ollama"], adapter_factory=floor_factory, now=now
            )
        breaker = await _breaker(conn, uid, "ollama")
        assert breaker["state"] == "OPEN" and breaker["failure_count"] == 0
        assert breaker["cooldown_expires_at"] == now + timedelta(seconds=COOLDOWN_FLOOR_SECONDS)

        plain_factory, _a, _e = scripted_factory({"groq": [http(500), http(500), http(500)]})
        for _ in range(3):
            with pytest.raises(ProvidersExhaustedError):
                await route_llm_request(
                    conn, user_id=uid, prompt="x", provider_chain=["groq"], adapter_factory=plain_factory, now=now
                )
        breaker = await _breaker(conn, uid, "groq")
        assert breaker["state"] == "OPEN" and breaker["failure_count"] == 3
        assert breaker["cooldown_expires_at"] == now + timedelta(seconds=COOLDOWN_FLOOR_SECONDS)
    finally:
        await conn.close()


async def test_429s_never_advance_the_trip_counter() -> None:
    """One real failure + two 429s: counter stays 1, circuit OPEN (busy != dead)."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini")
        factory, adapters, _events = scripted_factory({"gemini": [http(500), rate_limited(60), rate_limited(60)]})
        now = datetime.now(UTC)
        with pytest.raises(ProvidersExhaustedError):
            await route_llm_request(conn, user_id=uid, prompt="x", adapter_factory=factory, now=now)
        for _ in range(2):
            with pytest.raises(ProvidersExhaustedError):
                await route_llm_request(conn, user_id=uid, prompt="x", adapter_factory=factory, now=now)
        breaker = await _breaker(conn, uid, "gemini")
        assert breaker["state"] == "OPEN"
        assert breaker["failure_count"] == 1  # only the single 500 counted
        assert len(adapters["gemini"].calls) == 2  # third attempt skipped while OPEN
    finally:
        await conn.close()


# ----------------------------------------------------------------------- router
async def test_provider_calls_go_through_router_and_record_usage() -> None:
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini")
        factory, _adapters, _events = scripted_factory(
            {"gemini": [ok("hello agent", model="gemini-model", pt=12, ct=8, latency=6)]}
        )
        result = await route_llm_request(conn, user_id=uid, prompt="greet me", adapter_factory=factory)
        assert result.content == "hello agent"
        assert result.provider == "gemini" and result.model == "gemini-model"
        assert (result.prompt_tokens, result.completion_tokens, result.latency_ms) == (12, 8, 6)
        assert (
            await _count(
                conn,
                uid,
                "SELECT count(*) FROM provider_usage pu JOIN llm_providers lp ON lp.id = pu.provider_id "
                "WHERE pu.user_id = %s AND lp.name = 'gemini' AND pu.success AND pu.prompt_tokens = 12 "
                "AND pu.completion_tokens = 8 AND pu.latency_ms = 6",
                uid,
            )
            == 1
        )
    finally:
        await conn.close()


async def test_usage_tracking_keys_job_and_error_type() -> None:
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini")
        await _add_provider(conn, uid, "groq")
        job_id = await _add_job(conn, uid)

        ok_factory, _a, _e = scripted_factory({"gemini": [ok(pt=1, ct=2, latency=3)]})
        await route_llm_request(conn, user_id=uid, prompt="x", adapter_factory=ok_factory, job_id=job_id)

        fail_factory, _a, _e = scripted_factory({"groq": [http(500)]})
        with pytest.raises(ProvidersExhaustedError):
            await route_llm_request(
                conn, user_id=uid, prompt="x", provider_chain=["groq"], adapter_factory=fail_factory, job_id=job_id
            )

        async with DbContext(conn, uid).transaction() as db:
            rows = await (
                await db.execute(
                    "SELECT lp.name, pu.success, pu.error_type, pu.job_id FROM provider_usage pu "
                    "JOIN llm_providers lp ON lp.id = pu.provider_id WHERE pu.user_id = %s",
                    (str(uid),),
                )
            ).fetchall()
        assert {r[0] for r in rows} == {"gemini", "groq"}
        gem = next(r for r in rows if r[0] == "gemini")
        assert gem[1] is True and gem[2] is None and gem[3] == job_id
        groq = next(r for r in rows if r[0] == "groq")
        assert groq[1] is False and groq[2] == "server_error" and groq[3] == job_id
    finally:
        await conn.close()


async def test_llm_test_endpoint_probe() -> None:
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini", api_key="sk-probe")
        svc = LlmProviderService(conn)
        providers = await svc.list_providers(user_id=uid)
        provider_id = providers[0].id

        ok_factory, _a, _e = scripted_factory({"gemini": [ok("probe response", model="gemini-model", latency=9)]})
        probe = await svc.test_provider(user_id=uid, provider_id=provider_id, prompt="ping", adapter_factory=ok_factory)
        assert probe["success"] is True
        assert probe["response"] == "probe response"
        assert probe["latency_ms"] == 9
        assert probe["model"] == "gemini-model"

        fail_factory, _a, _e = scripted_factory({"gemini": [http(500)]})
        with pytest.raises(ProviderTestFailedError) as exc:
            await svc.test_provider(user_id=uid, provider_id=provider_id, prompt="ping", adapter_factory=fail_factory)
        assert exc.value.status == 422
        assert exc.value.code == "PROVIDER_TEST_FAILED"
        assert exc.value.details["provider"] == "gemini" and exc.value.details["status_code"] == 500
        _assert_envelope_shape(exc.value)

        ghost = uuid.uuid4()
        with pytest.raises(ProviderNotFoundError) as exc:
            await svc.test_provider(user_id=uid, provider_id=ghost, prompt="ping")
        assert exc.value.status == 404 and exc.value.code == "PROVIDER_NOT_FOUND"
    finally:
        await conn.close()


async def test_provider_chain_resolution_from_settings() -> None:
    """Default chain resolves by priority; inactive + missing names skipped (D15)."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "groq", priority=0)
        await _add_provider(conn, uid, "gemini", priority=10)
        await _add_provider(conn, uid, "ollama", priority=5)
        async with DbContext(conn, uid).transaction() as db:
            await db.execute("UPDATE llm_providers SET is_active = false WHERE name = 'ollama'")
        factory, _adapters, events = scripted_factory({"groq": [rate_limited(5)], "gemini": [ok()]})
        result = await route_llm_request(conn, user_id=uid, prompt="x", adapter_factory=factory)
        # groq (priority 0) beats gemini (priority 10) despite settings default order
        assert events == ["groq", "gemini"]
        assert result.provider == "gemini"
        assert "ollama" not in events  # inactive row skipped

        # empty active chain -> exhaustion path
        conn2, bag2 = await _register()
        try:
            with pytest.raises(ProvidersExhaustedError) as exc:
                await route_llm_request(conn2, user_id=bag2["result"].id, prompt="x")
            assert exc.value.status == 503
            assert (
                await _count(
                    conn2, bag2["result"].id, "SELECT count(*) FROM audit_logs WHERE action = 'all_providers_exhausted'"
                )
                == 1
            )
        finally:
            await conn2.close()

        # explicit provider_chain override is honored
        with pytest.raises(ProvidersExhaustedError):
            await route_llm_request(
                conn,
                user_id=uid,
                prompt="x",
                provider_chain=["groq"],
                adapter_factory=scripted_factory({"groq": [http(500)]})[0],
            )
    finally:
        await conn.close()


# ------------------------------------------------------------------- CRUD/RLS
async def test_provider_crud_rls_cross_user() -> None:
    conn_a, bag_a = await _register()
    try:
        uid_a = bag_a["result"].id
        await _add_provider(conn_a, uid_a, "gemini", api_key="super-secret-key")

        outs = await LlmProviderService(conn_a).list_providers(user_id=uid_a)
        assert len(outs) == 1
        assert "api_key" not in vars(outs[0])  # never echoed (D18)
        assert not any("super-secret-key" in str(getattr(outs[0], k)) for k in vars(outs[0]))

        conn_b, bag_b = await _register()
        try:
            uid_b = bag_b["result"].id
            assert await LlmProviderService(conn_b).list_providers(user_id=uid_b) == []
            with pytest.raises(ProviderNotFoundError):
                await LlmProviderService(conn_b).delete_provider(user_id=uid_b, provider_id=uuid.UUID(outs[0].id))
            with pytest.raises(ProviderNotFoundError):
                await LlmProviderService(conn_b).test_provider(
                    user_id=uid_b, provider_id=uuid.UUID(outs[0].id), prompt="x"
                )
            assert len(await LlmProviderService(conn_a).list_providers(user_id=uid_a)) == 1
        finally:
            await conn_b.close()
    finally:
        await conn_a.close()


async def test_api_key_at_rest_encrypted() -> None:
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini", api_key="sk-plaintext-secret")
        await _add_provider(conn, uid, "ollama")

        async with DbContext(conn, uid).transaction() as db:
            rows = await LlmRouterRepository(db).list_providers(uid)
        gem = next(r for r in rows if r["name"] == "gemini")
        oll = next(r for r in rows if r["name"] == "ollama")

        assert gem["api_key_encrypted"] != "sk-plaintext-secret"
        assert ":" in gem["api_key_encrypted"]  # nonce:ciphertext blob
        assert decrypt_provider_key(gem["api_key_encrypted"]) == "sk-plaintext-secret"

        original = os.environ["LLM_PROVIDER_MASTER_KEY"]
        try:
            os.environ["LLM_PROVIDER_MASTER_KEY"] = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
            with pytest.raises(DecryptionError):
                decrypt_provider_key(gem["api_key_encrypted"])
        finally:
            os.environ["LLM_PROVIDER_MASTER_KEY"] = original
        assert oll["api_key_encrypted"] is None  # keyless row stays nullable

        # corrupt stored blob at routing time -> provider failed, chain advances (D18)
        async with DbContext(conn, uid).transaction() as db:
            await db.execute("UPDATE llm_providers SET api_key_encrypted = %s WHERE name = 'gemini'", ("zz:zz",))
        factory, _adapters, _events = scripted_factory({"ollama": [ok()]})
        result = await route_llm_request(
            conn, user_id=uid, prompt="x", provider_chain=["gemini", "ollama"], adapter_factory=factory
        )
        assert result.provider == "ollama"
        assert await _count(conn, uid, "SELECT count(*) FROM provider_usage WHERE error_type = 'invalid_key'") == 1
        assert await _count(conn, uid, "SELECT count(*) FROM rate_limit_state") == 0  # decrypt failure never trips
    finally:
        await conn.close()


async def test_provider_not_found_is_404_for_test_and_delete() -> None:
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        ghost = uuid.uuid4()
        svc = LlmProviderService(conn)
        for coro in (
            svc.delete_provider(user_id=uid, provider_id=ghost),
            svc.test_provider(user_id=uid, provider_id=ghost, prompt="x"),
        ):
            with pytest.raises(ProviderNotFoundError) as exc:
                await coro
            assert exc.value.status == 404
            assert exc.value.code == "PROVIDER_NOT_FOUND"
            _assert_envelope_shape(exc.value)
        assert await _count(conn, uid, "SELECT count(*) FROM audit_logs WHERE action LIKE 'llm_provider_%%'") == 0
    finally:
        await conn.close()


async def test_provider_duplicate_is_409_case_insensitive() -> None:
    conn_a, bag_a = await _register()
    try:
        uid = bag_a["result"].id
        svc = LlmProviderService(conn_a)
        await svc.add_provider(user_id=uid, name="groq", base_url="http://groq/v1", model="m")
        with pytest.raises(ProviderDuplicateError) as exc:
            await svc.add_provider(user_id=uid, name="Groq", base_url="http://groq/v1", model="m")
        assert exc.value.status == 409
        assert exc.value.code == "PROVIDER_DUPLICATE"
        _assert_envelope_shape(exc.value)
        assert len(await svc.list_providers(user_id=uid)) == 1
        assert await _count(conn_a, uid, "SELECT count(*) FROM audit_logs WHERE action = 'llm_provider_added'") == 1

        conn_b, bag_b = await _register()
        try:
            # same name under another user is NOT a duplicate (B2 is app-layer, user-scoped)
            await LlmProviderService(conn_b).add_provider(
                user_id=bag_b["result"].id, name="groq", base_url="http://x", model="m"
            )
        finally:
            await conn_b.close()
    finally:
        await conn_a.close()


async def test_migration_027_name_check_and_registry_gate() -> None:
    """027's two gates: mixed-case rejected by DB; lowercase-unregistered passes DB but registry rejects."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        async with DbContext(conn, uid).transaction() as db:
            with pytest.raises(psycopg.errors.CheckViolation):
                await db.execute(
                    "INSERT INTO llm_providers (user_id, name, base_url, model) "
                    "VALUES (%s, 'Anthropic', 'http://x', 'm')",
                    (str(uid),),
                )
        async with DbContext(conn, uid).transaction() as db:
            await db.execute(
                "INSERT INTO llm_providers (user_id, name, base_url, model) VALUES (%s, 'anthropic', 'http://x', 'm')",
                (str(uid),),
            )
        with pytest.raises(ValidationError) as exc:
            await LlmProviderService(conn).add_provider(user_id=uid, name="anthropic", base_url="http://x", model="m")
        assert exc.value.status == 422 and exc.value.code == "VALIDATION_ERROR"

        await _add_provider(conn, uid, "gemini")
        factory, _adapters, events = scripted_factory({"gemini": [ok()]})
        result = await route_llm_request(
            conn, user_id=uid, prompt="x", provider_chain=["anthropic", "gemini"], adapter_factory=factory
        )
        assert result.provider == "gemini"  # anthropic skipped as unavailable (no adapter call)
        assert events == ["gemini"]
    finally:
        await conn.close()


# ------------------------------------------------------------------- registry
async def test_registry_maps_core_providers() -> None:
    assert set(spec_for(n) is not None for n in ("gemini", "ollama", "groq", "openrouter")) == {True}
    assert spec_for("groq").adapter is OpenAICompatibleAdapter
    assert spec_for("openrouter").adapter is OpenAICompatibleAdapter
    assert spec_for("gemini").adapter is GeminiAdapter
    assert spec_for("ollama").adapter is OllamaAdapter
    assert not is_registered("anthropic")


# --------------------------------------------------------------- no llm routes
def test_no_llm_routes_registered() -> None:
    assert not any(getattr(r, "path", "").startswith("/api/llm") for r in app.routes)


# --------------------------------------------------------------- adapters (D14)
def _capture_transport(cap: dict, *, status: int = 200, payload=None, headers=None) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        cap["url"] = str(request.url)
        cap["method"] = request.method
        cap["headers"] = dict(request.headers)
        cap["body"] = request.read().decode()
        return httpx.Response(status, json=payload or {}, headers=headers or {}, request=request)

    return httpx.MockTransport(handler)


def test_groq_adapter_wire_behavior() -> None:
    cap: dict = {}
    transport = _capture_transport(
        cap,
        payload={
            "model": "groq-model",
            "choices": [{"message": {"content": "groq ok"}}],
            "usage": {"prompt_tokens": 7, "completion_tokens": 9},
        },
    )
    adapter = OpenAICompatibleAdapter(transport=transport)
    resp = adapter.chat(
        prompt="hi",
        system_message="sys",
        model="groq-model",
        base_url="https://api.groq.com/openai/v1",
        api_key="k",
    )
    assert resp.status == "ok" and resp.content == "groq ok"
    assert (resp.prompt_tokens, resp.completion_tokens) == (7, 9)
    assert cap["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert cap["headers"].get("authorization") == "Bearer k"
    body = json.loads(cap["body"])
    assert body["messages"][0] == {"role": "system", "content": "sys"}

    ra_cap: dict = {}
    ra = OpenAICompatibleAdapter(transport=_capture_transport(ra_cap, status=429, headers={"Retry-After": "12"}))
    resp = ra.chat(prompt="hi", system_message=None, model="m", base_url="https://api.groq.com/openai/v1", api_key="k")
    assert resp.status == "http_error" and resp.status_code == 429
    assert resp.retry_after == 12 and resp.error_type == "rate_limited"

    bad_cap: dict = {}
    bad = OpenAICompatibleAdapter(transport=_capture_transport(bad_cap, status=401))
    resp = bad.chat(prompt="hi", system_message=None, model="m", base_url="https://api.groq.com/openai/v1", api_key="k")
    assert resp.error_type == "invalid_key"

    def timeouts(_request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow provider")

    slow = OpenAICompatibleAdapter(transport=httpx.MockTransport(timeouts))
    resp = slow.chat(
        prompt="hi", system_message=None, model="m", base_url="https://api.groq.com/openai/v1", api_key="k"
    )
    assert resp.status == "timeout" and resp.error_type == "timeout"


def test_openrouter_adapter_uses_openai_compatible_path() -> None:
    cap: dict = {}
    transport = _capture_transport(cap, payload={"choices": [{"message": {"content": "or ok"}}]})
    adapter = OpenAICompatibleAdapter(transport=transport)
    resp = adapter.chat(
        prompt="hi",
        system_message=None,
        model="openai/gpt-4o-mini",
        base_url="https://openrouter.ai/api/v1",
        api_key="k",
    )
    assert resp.status == "ok" and resp.content == "or ok"
    assert cap["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert cap["headers"].get("authorization") == "Bearer k"


def test_gemini_adapter_wire_behavior() -> None:
    cap: dict = {}
    transport = _capture_transport(
        cap,
        payload={
            "candidates": [{"content": {"parts": [{"text": "gemini ok"}]}}],
            "usageMetadata": {"promptTokenCount": 3, "candidatesTokenCount": 5},
        },
    )
    adapter = GeminiAdapter(transport=transport)
    resp = adapter.chat(
        prompt="hi",
        system_message="sys",
        model="gemini-2.0-flash",
        base_url="https://generativelanguage.googleapis.com",
        api_key="k",
        json_mode=True,
    )
    assert resp.status == "ok" and resp.content == "gemini ok"
    assert (resp.prompt_tokens, resp.completion_tokens) == (3, 5)
    assert ":generateContent" in cap["url"]
    assert cap["headers"].get("x-goog-api-key") == "k"
    body = json.loads(cap["body"])
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert body["contents"][0]["role"] == "user"

    ra_cap: dict = {}
    ra = GeminiAdapter(transport=_capture_transport(ra_cap, status=429, headers={"Retry-After": "9"}))
    resp = ra.chat(
        prompt="hi", system_message=None, model="m", base_url="https://generativelanguage.googleapis.com", api_key="k"
    )
    assert resp.status == "http_error" and resp.status_code == 429 and resp.retry_after == 9

    se_cap: dict = {}
    se = GeminiAdapter(transport=_capture_transport(se_cap, status=503))
    resp = se.chat(
        prompt="hi", system_message=None, model="m", base_url="https://generativelanguage.googleapis.com", api_key="k"
    )
    assert resp.status_code == 503 and resp.error_type == "server_error"

    def drop(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused")

    conn_refused = GeminiAdapter(transport=httpx.MockTransport(drop))
    resp = conn_refused.chat(
        prompt="hi", system_message=None, model="m", base_url="https://generativelanguage.googleapis.com", api_key="k"
    )
    assert resp.status == "unavailable" and resp.error_type == "connection"


def test_ollama_adapter_wire_behavior() -> None:
    cap: dict = {}
    transport = _capture_transport(
        cap, payload={"message": {"content": "ollama ok"}, "prompt_eval_count": 4, "eval_count": 6}
    )
    adapter = OllamaAdapter(transport=transport)
    resp = adapter.chat(
        prompt="hi",
        system_message=None,
        model="llama3",
        base_url="http://localhost:11434",
        json_mode=True,
    )
    assert resp.status == "ok" and resp.content == "ollama ok"
    assert (resp.prompt_tokens, resp.completion_tokens) == (4, 6)
    assert cap["url"] == "http://localhost:11434/api/chat"
    body = json.loads(cap["body"])
    assert body["stream"] is False and body["format"] == "json"

    loading_cap: dict = {}
    loading = OllamaAdapter(transport=_capture_transport(loading_cap, status=503))
    resp = loading.chat(prompt="hi", system_message=None, model="m", base_url="http://localhost:11434")
    assert resp.status == "unavailable" and resp.error_type == "model_loading"

    def drop(_request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("ollama not running")

    down = OllamaAdapter(transport=httpx.MockTransport(drop))
    resp = down.chat(prompt="hi", system_message=None, model="m", base_url="http://localhost:11434")
    assert resp.status == "unavailable" and resp.error_type == "connection"


def test_adapters_map_nonjson_200_body_to_unparseable_body() -> None:
    """A 200 whose body is not valid JSON must map to http_error, never raise (D14 contract)."""

    def html_body(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>not json</html>", request=request)

    for adapter, url in [
        (OpenAICompatibleAdapter(transport=httpx.MockTransport(html_body)), "https://api.groq.com/openai/v1"),
        (GeminiAdapter(transport=httpx.MockTransport(html_body)), "https://generativelanguage.googleapis.com"),
        (OllamaAdapter(transport=httpx.MockTransport(html_body)), "http://localhost:11434"),
    ]:
        resp = adapter.chat(prompt="hi", system_message=None, model="m", base_url=url, api_key="k")
        assert resp.status == "http_error" and resp.error_type == "unparseable_body"


# ------------------------------------------------------ mid-chain unavailable (B4)
async def test_mid_chain_unavailable_skipped_not_failed() -> None:
    """Ollama 503/model-loading -> skipped (no breaker transition), groq succeeds."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini", priority=0)
        await _add_provider(conn, uid, "ollama", priority=1)
        await _add_provider(conn, uid, "groq", priority=2)
        factory, _adapters, events = scripted_factory(
            {"gemini": [http(500)], "ollama": [unavailable()], "groq": [ok()]}
        )
        result = await route_llm_request(
            conn, user_id=uid, prompt="x", provider_chain=["gemini", "ollama", "groq"], adapter_factory=factory
        )
        assert result.provider == "groq"
        assert events == ["gemini", "ollama", "groq"]
        assert await _breaker(conn, uid, "ollama") is None  # skip is not a trip — no breaker row
        assert await _count(conn, uid, "SELECT count(*) FROM provider_usage WHERE error_type = 'unavailable'") == 1

        # companion: every provider runtime-unavailable -> each skipped -> exhaustion
        conn2, bag2 = await _register()
        try:
            uid2 = bag2["result"].id
            await _add_provider(conn2, uid2, "ollama", priority=0)
            await _add_provider(conn2, uid2, "groq", priority=1)
            all_down = scripted_factory({"ollama": [unavailable()], "groq": [unavailable(error_type="connection")]})[0]
            with pytest.raises(ProvidersExhaustedError) as exc:
                await route_llm_request(
                    conn2,
                    user_id=uid2,
                    prompt="x",
                    provider_chain=["ollama", "groq"],
                    adapter_factory=all_down,
                )
            assert exc.value.status == 503
            assert (
                await _count(conn2, uid2, "SELECT count(*) FROM audit_logs WHERE action = 'all_providers_exhausted'")
                == 1
            )
        finally:
            await conn2.close()
    finally:
        await conn.close()


# ------------------------------------------------------------------ D20 JSON
async def test_parse_llm_json_fenced() -> None:
    parsed = parse_llm_json('Sure! Here is the result:\n```json\n{"title": "Job", "score": 42}\n```\nHope it helps.')
    assert parsed == {"title": "Job", "score": 42}
    bare = parse_llm_json('```\n{"a": [1, 2]}\n```')
    assert bare == {"a": [1, 2]}
    assert parse_llm_json("no json here") is None
    assert parse_llm_json("") is None


async def test_parse_llm_json_wrapper_and_truncation_repair() -> None:
    wrapper = parse_llm_json('{"result": {"title": "Job", "score": 7}}')
    assert wrapper == {"title": "Job", "score": 7}
    output_wrapper = parse_llm_json('Some prose {"output": [1, 2, 3]} tail')
    assert output_wrapper == [1, 2, 3]
    truncated = parse_llm_json('{"title": "Job", "score": 4')
    assert truncated == {"title": "Job", "score": 4}
    nested = parse_llm_json('{"result": {"a": [1, 2')
    assert nested == {"a": [1, 2]}


class _Analysis(BaseModel):
    title: str
    score: int


async def test_structured_invalid_advances_next_with_bounded_repair() -> None:
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini", priority=0)
        await _add_provider(conn, uid, "groq", priority=1)
        factory, adapters, _events = scripted_factory(
            {
                "gemini": [ok("this is not json at all"), ok("still not json")],
                "groq": [ok('{"title": "Real Job", "score": 9}')],
            }
        )
        validated = await generate_structured(
            conn,
            user_id=uid,
            prompt="extract",
            system_message=None,
            output_model=_Analysis,
            provider_chain=["gemini", "groq"],
            adapter_factory=factory,
        )
        assert isinstance(validated, _Analysis)
        assert validated.title == "Real Job" and validated.score == 9
        # bounded repair: one extra gemini call, then failover to groq
        assert len(adapters["gemini"].calls) == 2
        assert "Return ONLY valid JSON" in adapters["gemini"].calls[1]["prompt"]
        assert len(adapters["groq"].calls) == 1
        assert await _count(conn, uid, "SELECT count(*) FROM provider_usage WHERE error_type = 'invalid_json'") == 2
        # shape failures never trip the circuit
        breaker = await _breaker(conn, uid, "gemini")
        assert breaker is None or (breaker["state"] == "CLOSED" and breaker["failure_count"] == 0)
    finally:
        await conn.close()


def test_json_mode_flag_diffs_per_provider_on_wire() -> None:
    """json_mode=true carries the provider-native flag; default leaves the body untouched (D20)."""
    cap: dict = {}

    off = OpenAICompatibleAdapter(
        transport=_capture_transport(cap, payload={"choices": [{"message": {"content": "x"}}]})
    )
    resp = off.chat(
        prompt="plain", system_message=None, model="m", base_url="https://api.groq.com/openai/v1", api_key="k"
    )
    assert resp.status == "ok"
    body = json.loads(cap["body"])
    assert "response_format" not in body
    assert body["messages"][-1]["content"] == "plain"

    on = OpenAICompatibleAdapter(
        transport=_capture_transport(cap, payload={"choices": [{"message": {"content": "x"}}]})
    )
    resp = on.chat(
        prompt="plain",
        system_message=None,
        model="m",
        base_url="https://api.groq.com/openai/v1",
        api_key="k",
        json_mode=True,
    )
    assert resp.status == "ok"
    assert json.loads(cap["body"])["response_format"] == {"type": "json_object"}

    on_schema = OpenAICompatibleAdapter(
        transport=_capture_transport(cap, payload={"choices": [{"message": {"content": "x"}}]})
    )
    resp = on_schema.chat(
        prompt="plain",
        system_message=None,
        model="m",
        base_url="https://api.groq.com/openai/v1",
        api_key="k",
        json_mode=True,
        output_schema={"type": "object", "properties": {"title": {"type": "string"}}},
    )
    assert resp.status == "ok"
    assert json.loads(cap["body"])["response_format"]["type"] == "json_schema"

    gem = GeminiAdapter(
        transport=_capture_transport(cap, payload={"candidates": [{"content": {"parts": [{"text": "x"}]}}]})
    )
    resp = gem.chat(
        prompt="plain",
        system_message=None,
        model="m",
        base_url="https://generativelanguage.googleapis.com",
        api_key="k",
        json_mode=True,
    )
    assert resp.status == "ok"
    assert json.loads(cap["body"])["generationConfig"]["responseMimeType"] == "application/json"

    oll = OllamaAdapter(transport=_capture_transport(cap, payload={"message": {"content": "x"}}))
    resp = oll.chat(prompt="plain", system_message=None, model="m", base_url="http://localhost:11434", json_mode=True)
    assert resp.status == "ok"
    assert json.loads(cap["body"])["format"] == "json"


# ------------------------------------------------------ settings relaxation (D19)
async def test_llm_chain_settings_rippled_to_registry_membership() -> None:
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        svc = SettingsService(conn)
        assert await svc.get(user_id=uid) == {
            "chat_mode": "bot",
            "theme": "dark",
            "auto_approve_threshold": 80,
            "notifications_enabled": True,
            "llm_chain": DEFAULT_CHAIN,
        }
        merged = await svc.update(user_id=uid, updates={"llm_chain": ["gemini", "ollama"]})
        assert merged["llm_chain"] == ["gemini", "ollama"]
        with pytest.raises(SettingsValueInvalidError):
            await svc.update(user_id=uid, updates={"llm_chain": ["gemini", "anthropic"]})
    finally:
        await conn.close()


# ------------------------------------------------------------ invalid key (B1)
async def test_invalid_key_marks_provider_failed_and_advances() -> None:
    """401/invalid-key marks the provider failed (audited), chain advances (B1)."""
    conn, bag = await _register()
    try:
        uid = bag["result"].id
        await _add_provider(conn, uid, "gemini", api_key="sk-wrong")
        await _add_provider(conn, uid, "ollama")
        factory, _adapters, events = scripted_factory({"gemini": [invalid_key()], "ollama": [ok()]})
        result = await route_llm_request(
            conn, user_id=uid, prompt="x", provider_chain=["gemini", "ollama"], adapter_factory=factory
        )
        assert result.provider == "ollama"
        assert events == ["gemini", "ollama"]
        assert await _count(conn, uid, "SELECT count(*) FROM provider_usage WHERE error_type = 'invalid_key'") == 1
        assert await _count(conn, uid, "SELECT count(*) FROM audit_logs WHERE action = 'llm_provider_failed'") == 1
    finally:
        await conn.close()
