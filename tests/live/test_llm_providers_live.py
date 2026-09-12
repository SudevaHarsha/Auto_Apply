"""Live LLM provider smoke tests — opt-in, end-to-end over the real wire (S4).

The complete production flow, with real API keys from ``.env.live``:

  Phase 1  keys land in ``llm_providers`` through ``LlmProviderService.add_provider``
           (AES-256-GCM ciphertext at rest, D18) and are verified to decrypt back;
  Phase 2  ``route_llm_request`` reads the key BACK from the DB row, decrypts it
           in-memory and makes a REAL HTTP call (default adapter factory, no mock);
  Phase 3  ``generate_structured`` live JSON-mode lane (D20);
  Phase 4  ``test_provider`` live probe;
  Phase 5  CRUD on the stored rows (duplicate 409, delete clears row + breaker);
  Failover invalid real key (vendor 401/400 on the wire) -> chain advances to a
  stored valid key provider;
  Breaker   one bad-key gemini: 3 real failures TRIP -> OPEN; the 4th call is
            skipped by the breaker (no network); past cooldown, exactly one
            HALF_OPEN trial runs and its failure re-trips to OPEN.

Enabled ONLY by ``-Target test-integration-live`` (sets ``RUN_LIVE_LLM=1``) with real
keys in the gitignored ``.env.live``; placeholder values are ignored. A provider that
replies 429/quota at runtime is treated as environmental (skip); anything else fails
the suite. Cost per run: a handful of requests (free tiers ~nothing).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
import pytest_asyncio
from pydantic import BaseModel, ConfigDict

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("LLM_PROVIDER_MASTER_KEY", "0123456789abcdef0123456789abcdef")

from backend.app.auth.service import AuthService
from backend.app.db.context import DbContext
from backend.app.db.repositories.llm_router_repository import LlmRouterRepository
from backend.app.llm.crypto import decrypt_provider_key
from backend.app.llm.errors import (
    ProviderDuplicateError,
    ProvidersExhaustedError,
    ProviderTestFailedError,
)
from backend.app.llm.router import generate_structured, route_llm_request
from backend.app.llm.service import LlmProviderService, ProviderOut

pytestmark = pytest.mark.live

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5435/autoapply")

PASSWORD = "Str0ng!password"

CLOUD_PROVIDERS = ("gemini", "groq", "openrouter")
KEY_ENV = {
    "gemini": "LIVE_GEMINI_API_KEY",
    "groq": "LIVE_GROQ_API_KEY",
    "openrouter": "LIVE_OPENROUTER_API_KEY",
}

ROUTE_PROMPT = "Reply with exactly the single word: ok"
STRUCTURED_PROMPT = 'Return JSON with one field "greeting" set to the word hi.'


class LiveGreeting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    greeting: str


def _key(name: str) -> str | None:
    """Key from the environment; None for unset or placeholder ('PASTE_...') values."""
    raw = os.environ.get(KEY_ENV[name], "")
    stripped = raw.strip()
    if not stripped or stripped.upper().startswith("PASTE_"):
        return None
    return stripped


def _configured() -> list[tuple[str, str | None]]:
    cfgs: list[tuple[str, str | None]] = [(name, _key(name)) for name in CLOUD_PROVIDERS if _key(name)]
    url = os.environ.get("LIVE_OLLAMA_URL", "").strip()
    if url and not url.upper().startswith("PASTE_"):
        cfgs.append(("ollama", None))
    return cfgs


def _live_gate() -> list[tuple[str, str | None]]:
    if os.environ.get("RUN_LIVE_LLM") != "1":
        pytest.skip("live provider tests disabled; run .\\tasks.ps1 -Target test-integration-live")
    cfgs = _configured()
    if not cfgs:
        pytest.fail("RUN_LIVE_LLM=1 but no LIVE_*_API_KEY configured - paste real keys into .env.live")
    return cfgs


async def _conn() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(APP_URL)


def _mail(tag: str = "live") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.com"


async def _register() -> tuple[psycopg.AsyncConnection, object]:
    conn = await _conn()
    try:
        result = await AuthService(conn).register(email=_mail(), password=PASSWORD, name="Live LLM Tester")
    except Exception:
        await conn.close()
        raise
    return conn, result


async def _add(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    name: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    priority: int = 0,
) -> ProviderOut:
    """Real ``add_provider``: registry gate + AES-256-GCM encrypt + audit, exactly as production."""
    return await LlmProviderService(conn).add_provider(
        user_id=user_id, name=name, base_url=base_url, api_key=api_key, priority=priority
    )


async def _add_configured(
    conn: psycopg.AsyncConnection, user_id: uuid.UUID, cfgs: list[tuple[str, str | None]]
) -> dict[str, uuid.UUID]:
    ids: dict[str, uuid.UUID] = {}
    for index, (name, key) in enumerate(cfgs):
        base_url = os.environ.get("LIVE_OLLAMA_URL", "").strip() if name == "ollama" else None
        out = await _add(conn, user_id, name, api_key=key, base_url=base_url, priority=index)
        ids[name] = uuid.UUID(out.id)
    return ids


async def _count(conn: psycopg.AsyncConnection, user_id: uuid.UUID, query: str, *params: object) -> int:
    async with DbContext(conn, user_id).transaction() as db:
        n = await db.fetch_scalar(query, tuple(params))
    return int(n or 0)


async def _breaker(conn: psycopg.AsyncConnection, user_id: uuid.UUID, name: str) -> dict | None:
    async with DbContext(conn, user_id).transaction() as db:
        return await LlmRouterRepository(db).get_breaker(user_id, name)


async def _failure_types(conn: psycopg.AsyncConnection, user_id: uuid.UUID) -> set[str]:
    async with DbContext(conn, user_id).transaction() as db:
        rows = await (
            await db.execute(
                "SELECT DISTINCT error_type FROM provider_usage "
                "WHERE user_id = %s AND success = false AND error_type IS NOT NULL",
                (str(user_id),),
            )
        ).fetchall()
    return {row[0] for row in rows}


async def _safe_route(conn: psycopg.AsyncConnection, user_id: uuid.UUID, prompt: str, *, provider_chain=None):
    """Live route; a runtime 429/quota outcome is skipped as environmental, all else fails."""
    try:
        return await route_llm_request(conn, user_id=user_id, prompt=prompt, provider_chain=provider_chain)
    except ProvidersExhaustedError as exc:
        types = await _failure_types(conn, user_id)
        if types == {"rate_limited"}:
            pytest.skip(f"provider(s) replied 429/quota during live run (error_types={sorted(types)}): {exc}")
        raise


@pytest_asyncio.fixture(scope="module")
async def live_ctx() -> dict:
    """One scratch user; every configured provider is stored with its real key, once."""
    cfgs = _live_gate()
    conn, result = await _register()
    user_id = result.id
    try:
        provider_ids = await _add_configured(conn, user_id, cfgs)
    except Exception:
        await conn.close()
        raise
    yield {"conn": conn, "user_id": user_id, "provider_ids": provider_ids, "cfgs": cfgs}
    await conn.close()


async def test_phase1_provider_rows_persisted_encrypted_at_rest(live_ctx: dict) -> None:
    """Phase 1 - rows are kept in llm_providers first; keys are ciphertext that decrypts back (D18)."""
    conn, user_id, cfgs = live_ctx["conn"], live_ctx["user_id"], live_ctx["cfgs"]
    expected = [name for name, _ in cfgs]
    rows = await LlmProviderService(conn).list_providers(user_id=user_id)
    assert [p.name for p in rows] == expected, "providers are listed in priority order"
    assert all(not hasattr(p, "api_key") for p in rows), "api_key must never be exposed on the output"
    for name, key in cfgs:
        if key is None:
            continue
        async with DbContext(conn, user_id).transaction() as db:
            row = await (
                await db.execute(
                    "SELECT api_key_encrypted FROM llm_providers WHERE user_id = %s AND name = %s",
                    (str(user_id), name),
                )
            ).fetchone()
        blob = row[0]
        assert blob, f"{name}: no ciphertext stored in llm_providers"
        assert blob != key, f"{name}: API key stored in plaintext!"
        assert decrypt_provider_key(blob) == key, f"{name}: at-rest decryption round-trip failed"


async def test_phase2_live_route_reads_key_from_db_and_calls(live_ctx: dict) -> None:
    """Phase 2 - real wire call whose API key is read and decrypted FROM the stored row."""
    conn, user_id, cfgs = live_ctx["conn"], live_ctx["user_id"], live_ctx["cfgs"]
    top_name = cfgs[0][0]
    result = await _safe_route(conn, user_id, ROUTE_PROMPT)
    assert result.provider == top_name, f"expected top-priority provider {top_name} to answer, got {result.provider}"
    assert result.content.strip(), "live provider returned an empty response"
    assert result.prompt_tokens > 0 and result.completion_tokens > 0, "usage tokens not parsed from live response"
    assert result.latency_ms > 0
    assert (
        await _count(
            conn,
            user_id,
            "SELECT count(*) FROM provider_usage pu JOIN llm_providers lp ON lp.id = pu.provider_id "
            "WHERE pu.user_id = %s AND lp.name = %s AND pu.success "
            "AND pu.prompt_tokens > 0 AND pu.completion_tokens > 0",
            user_id,
            result.provider,
        )
        == 1
    ), "no successful usage row for the live call"
    breaker = await _breaker(conn, user_id, result.provider)
    assert breaker is None or breaker["state"] == "CLOSED", "success must leave the breaker closed/absent"


async def test_phase3_live_generate_structured(live_ctx: dict) -> None:
    """Phase 3 - the D20 JSON lane over the real wire returns a validated model."""
    conn, user_id = live_ctx["conn"], live_ctx["user_id"]
    try:
        out = await generate_structured(
            conn,
            user_id=user_id,
            prompt=STRUCTURED_PROMPT,
            system_message="You are an API that returns ONLY valid JSON, never prose.",
            output_model=LiveGreeting,
        )
    except ProvidersExhaustedError as exc:
        types = await _failure_types(conn, user_id)
        if types == {"rate_limited"}:
            pytest.skip(f"provider(s) replied 429/quota during live structured run ({sorted(types)}): {exc}")
        raise
    assert isinstance(out, LiveGreeting), "generate_structured must return the validated pydantic model"
    assert out.greeting, "structured live response missing the greeting field"


async def test_phase4_live_test_provider_probe(live_ctx: dict) -> None:
    """Phase 4 - the one-shot probe hits the real provider with the stored key."""
    conn, user_id, provider_ids, cfgs = (
        live_ctx["conn"],
        live_ctx["user_id"],
        live_ctx["provider_ids"],
        live_ctx["cfgs"],
    )
    top_name = cfgs[0][0]
    try:
        res = await LlmProviderService(conn).test_provider(
            user_id=user_id, provider_id=provider_ids[top_name], prompt=ROUTE_PROMPT
        )
    except ProviderTestFailedError as exc:
        if exc.details.get("status_code") == 429:
            pytest.skip(f"probe hit 429/quota for {top_name}")
        raise
    assert res["success"] is True and res["response"] and res["model"], "live probe must succeed with stored key"


async def test_phase5_crud_on_stored_rows(live_ctx: dict) -> None:
    """Phase 5 - duplicate add is 409; delete removes the row and its breaker state atomically."""
    conn, user_id, provider_ids, cfgs = (
        live_ctx["conn"],
        live_ctx["user_id"],
        live_ctx["provider_ids"],
        live_ctx["cfgs"],
    )
    top_name, top_key = cfgs[0]
    with pytest.raises(ProviderDuplicateError):
        await _add(conn, user_id, top_name, api_key=top_key)
    await LlmProviderService(conn).delete_provider(user_id=user_id, provider_id=provider_ids[top_name])
    assert (
        await _count(
            conn,
            user_id,
            "SELECT count(*) FROM llm_providers WHERE user_id = %s AND id = %s",
            user_id,
            str(provider_ids[top_name]),
        )
        == 0
    ), "delete_provider must remove the row"
    assert await _breaker(conn, user_id, top_name) is None, "delete_provider must clear breaker state atomically"


async def test_live_failover_invalid_key_to_valid() -> None:
    """Real invalid key -> chain advances past it to the stored valid key provider.

    The vendor's status code for a bad key is not assumed (Gemini 400s, OpenAI-style
    APIs 401); exact 401->invalid_key classification is pinned offline by fake
    transports. Here we only require: one failed usage row for the bad provider,
    one success for the good one, and the audit entry.
    """
    cfgs = _live_gate()
    cloud = {name for name, _ in cfgs if name != "ollama"}
    if not cloud:
        pytest.skip("no cloud provider keys configured - failover needs a real 401 plus a valid key")
    good_name = "groq" if "groq" in cloud else sorted(cloud)[0]
    good_key = next(key for name, key in cfgs if name == good_name)
    bad_name = next(name for name in CLOUD_PROVIDERS if name != good_name)
    conn, result = await _register()
    user_id = result.id
    try:
        await _add(conn, user_id, bad_name, api_key=f"sk-invalid-live-{uuid.uuid4().hex}", priority=0)
        await _add(conn, user_id, good_name, api_key=good_key, priority=1)
        resp = await _safe_route(conn, user_id, ROUTE_PROMPT, provider_chain=[bad_name, good_name])
        assert resp.provider == good_name, "chain must fail over past the invalid-key provider"
        assert (
            await _count(
                conn,
                user_id,
                "SELECT count(*) FROM provider_usage pu JOIN llm_providers lp ON lp.id = pu.provider_id "
                "WHERE pu.user_id = %s AND lp.name = %s AND pu.success = false",
                user_id,
                bad_name,
            )
            == 1
        ), "the invalid real key must record exactly one failed usage row"
        assert (
            await _count(
                conn,
                user_id,
                "SELECT count(*) FROM provider_usage WHERE user_id = %s AND success = true",
                user_id,
            )
            == 1
        ), "the valid-key provider must record the success usage row"
        assert (
            await _count(
                conn,
                user_id,
                "SELECT count(*) FROM audit_logs WHERE user_id = %s AND action = 'llm_provider_failed'",
                user_id,
            )
            == 1
        ), "live 401 must be audited as llm_provider_failed"
    finally:
        await conn.close()


async def test_live_breaker_real_gemini_failures_trip_open_skip_halfopen() -> None:
    """Single bad-key gemini over the real wire -> full breaker lifecycle.

    Three real 400s increment the consecutive-failure counter and TRIP the breaker
    to OPEN; a 4th call within cooldown is skipped by the breaker (no network call,
    'none resolved'); simulating cooldown expiry via ``now`` lets exactly one
    HALF_OPEN trial through, whose real failure re-trips the circuit to OPEN.
    """
    _live_gate()
    conn, result = await _register()
    user_id = result.id
    try:
        await _add(conn, user_id, "gemini", api_key=f"sk-invalid-live-{uuid.uuid4().hex}")

        for _ in range(3):
            with pytest.raises(ProvidersExhaustedError) as excinfo:
                await route_llm_request(conn, user_id=user_id, prompt=ROUTE_PROMPT)
            assert "gemini" in str(excinfo.value), "bad-key gemini must be attempted each time"

        breaker = await _breaker(conn, user_id, "gemini")
        assert breaker is not None, "breaker row must exist after three failures"
        assert breaker["state"] == "OPEN", f"expected OPEN after 3 real failures, got {breaker['state']}"
        assert breaker["failure_count"] == 3, breaker
        assert breaker["cooldown_expires_at"] is not None, "OPEN must carry a cooldown deadline"
        assert (
            await _count(
                conn,
                user_id,
                "SELECT count(*) FROM provider_usage pu JOIN llm_providers lp ON lp.id = pu.provider_id "
                "WHERE pu.user_id = %s AND lp.name = %s AND pu.success = false",
                user_id,
                "gemini",
            )
            == 3
        ), "three real failures must be recorded in provider_usage"

        with pytest.raises(ProvidersExhaustedError) as excinfo:
            await route_llm_request(conn, user_id=user_id, prompt=ROUTE_PROMPT)
        assert "none resolved" in str(excinfo.value), "OPEN + cooldown must skip the provider entirely"
        assert (
            await _count(
                conn,
                user_id,
                "SELECT count(*) FROM provider_usage pu JOIN llm_providers lp ON lp.id = pu.provider_id "
                "WHERE pu.user_id = %s AND lp.name = %s AND pu.success = false",
                user_id,
                "gemini",
            )
            == 3
        ), "breaker skip must not dial the provider (no extra usage row)"

        future = datetime.now(UTC) + timedelta(seconds=120)
        with pytest.raises(ProvidersExhaustedError) as excinfo:
            await route_llm_request(conn, user_id=user_id, prompt=ROUTE_PROMPT, now=future)
        assert "gemini" in str(excinfo.value), "past cooldown the HALF_OPEN trial must be attempted"
        breaker = await _breaker(conn, user_id, "gemini")
        assert breaker["state"] == "OPEN", "trial failure must re-trip the breaker to OPEN"
        assert breaker["failure_count"] >= 4, breaker
    finally:
        await conn.close()
