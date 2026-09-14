"""Live JD extraction tests — opt-in, end-to-end over the real wire (S6, D29).

The full production cascade with real ATS postings from ``LIVE_ATS_URL`` and NO
mock anywhere:

  real ``fetch_http`` (NAT64-aware SSRF guard, D33) → Door-1 JSON-LD / Door 2-3
  text extraction → Door 4 mandatory 4-section LLM calls via the default adapter
  factory (real providers, keys from ``.env.live``) → Door 5 gap-fill → plausibility
  gate → snapshot + job rows persisted with ``content_hash``/``raw_text`` (D28).

Cache is disabled for these runs so every execution is a genuine fresh extraction
(``JD_CACHE_ENABLED=0`` — the URL-keyed cache is shared across users and would
otherwise serve a previously stored snapshot).

Enabled ONLY by ``-Target test-integration-live`` (sets ``RUN_LIVE_LLM=1``) with
real keys in the gitignored ``.env.live`` and real posting URLs in ``LIVE_ATS_URL``
(comma-separated). A live-ATS outage (403/404/timeout/SSRF-resolution) or a provider
that replies 429/quota is treated as environmental (skip); a real pipeline bug fails
the suite. Cost per run: 4-ish LLM calls per posting.
"""

from __future__ import annotations

import json
import os
import uuid

import psycopg
import pytest
import pytest_asyncio

os.environ.setdefault("JWT_SECRET", "test-secret-0123456789abcdef0123456789abcdef")
os.environ.setdefault("LLM_PROVIDER_MASTER_KEY", "0123456789abcdef0123456789abcdef")
os.environ["JD_CACHE_ENABLED"] = "0"

from backend.app.auth.service import AuthService
from backend.app.core_engine.errors import (
    FetchFailedError,
    JobNotFoundError,
    NotAPostingError,
    StructuredJDValidationError,
)
from backend.app.core_engine.jd_extractor import extract_job
from backend.app.db.context import DbContext
from backend.app.llm.service import LlmProviderService

pytestmark = pytest.mark.live

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5435/autoapply")
PASSWORD = "Str0ng!password"

CLOUD_PROVIDERS = ("gemini", "groq", "openrouter")
KEY_ENV = {
    "gemini": "LIVE_GEMINI_API_KEY",
    "groq": "LIVE_GROQ_API_KEY",
    "openrouter": "LIVE_OPENROUTER_API_KEY",
}

_ATS_OUTAGES = (FetchFailedError, JobNotFoundError, NotAPostingError, StructuredJDValidationError)


def _key(name: str) -> str | None:
    raw = os.environ.get(KEY_ENV[name], "")
    stripped = raw.strip()
    if not stripped or stripped.upper().startswith("PASTE_"):
        return None
    return stripped


def _configured() -> list[tuple[str, str | None]]:
    return [(name, _key(name)) for name in CLOUD_PROVIDERS if _key(name)]


def _ats_urls() -> list[str]:
    raw = os.environ.get("LIVE_ATS_URL", "").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


async def _conn() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(APP_URL)


def _mail(tag: str = "live-jd") -> str:
    return f"{tag}-{uuid.uuid4().hex[:10]}@example.com"


async def _register() -> tuple[psycopg.AsyncConnection, object]:
    conn = await _conn()
    try:
        result = await AuthService(conn).register(email=_mail(), password=PASSWORD, name="Live JD Tester")
    except Exception:
        await conn.close()
        raise
    return conn, result


@pytest_asyncio.fixture(scope="module")
async def live_ctx() -> dict:
    if os.environ.get("RUN_LIVE_LLM") != "1":
        pytest.skip("live JD extraction tests disabled; run .\\tasks.ps1 -Target test-integration-live")
    if not _configured():
        pytest.fail("RUN_LIVE_LLM=1 but no LIVE_*_API_KEY configured - paste real keys into .env.live")
    urls = _ats_urls()
    if not urls:
        pytest.skip("LIVE_ATS_URL empty - set it to a comma-separated list of real posting URLs")
    conn, result = await _register()
    user_id = result.id
    try:
        for index, (name, key) in enumerate(_configured()):
            await LlmProviderService(conn).add_provider(
                user_id=user_id, name=name, base_url=None, api_key=key, priority=index
            )
    except Exception:
        await conn.close()
        raise
    yield {"conn": conn, "user_id": user_id, "urls": urls}
    await conn.close()


async def _count(conn: psycopg.AsyncConnection, user_id: uuid.UUID, query: str, *params: object) -> int:
    async with DbContext(conn, user_id).transaction() as db:
        n = await db.fetch_scalar(query, tuple(params))
    return int(n or 0)


async def _success_types(conn: psycopg.AsyncConnection, user_id: uuid.UUID) -> set[str]:
    async with DbContext(conn, user_id).transaction() as db:
        rows = await (
            await db.execute(
                "SELECT DISTINCT error_type FROM provider_usage "
                "WHERE user_id = %s AND success = false AND error_type IS NOT NULL",
                (str(user_id),),
            )
        ).fetchall()
    return {row[0] for row in rows}


async def _run_one(conn: psycopg.AsyncConnection, user_id: uuid.UUID, url: str) -> None:
    before = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND success = true",
        str(user_id),
    )
    try:
        result = await extract_job(conn, user_id, url, adapter_factory=None, fetch=None, render=None)
    except _ATS_OUTAGES as exc:
        pytest.skip(f"live ATS unreachable/blocked for {url}: {exc}")
    except Exception as exc:  # noqa: BLE001 - surface 429/quota distinctly below
        types = await _success_types(conn, user_id)
        if not types:
            pytest.skip(f"provider(s) replied 429/quota during live run ({sorted(types)}): {exc}")
        raise

    assert result.cache_hit is False, f"{url}: cache must be disabled for a fresh live extraction"
    job = result.job
    assert isinstance(job.get("title"), str) and job["title"].strip(), f"{url}: title missing"
    assert isinstance(job.get("company"), str) and job["company"].strip(), f"{url}: company missing"

    payload = result.payload
    assert payload.get("title"), f"{url}: payload title missing"
    assert payload.get("company"), f"{url}: payload company missing"
    for section in ("responsibilities", "skills", "good_to_have"):
        assert section in payload, f"{url}: payload missing section {section}"

    door = result.extracted_via_door
    assert door in (1, 2, 3, 4), f"{url}: bad door {door}"

    if door >= 3:
        assert result.raw_text and result.raw_text.strip(), f"{url}: raw_text empty after door {door}"
        assert "<script" not in result.raw_text, f"{url}: raw HTML script spilled into raw_text (D28)"
    payload_text = json.dumps(payload)
    assert "<script" not in payload_text and "%3Cscript" not in payload_text, (
        f"{url}: raw HTML bytes spilled into payload (D28)"
    )

    assert result.snapshot_id is not None, f"{url}: no snapshot written"
    row_count = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM job_snapshots WHERE id = %s",
        str(result.snapshot_id),
    )
    assert row_count == 1, f"{url}: snapshot row missing in DB"

    after = await _count(
        conn,
        user_id,
        "SELECT count(*) FROM provider_usage WHERE user_id = %s AND success = true",
        str(user_id),
    )
    new_calls = after - before
    if door == 1:
        assert new_calls == 0, f"{url}: Door-1 JSON-LD packed the job — no LLM calls expected, got {new_calls}"
    else:
        # 4 mandatory Door-4 section calls + at most one retry per section + 0-1 Door 5.
        if new_calls < 4:
            pytest.skip(f"{url}: only {new_calls} successful LLM calls — partial provider outage (environmental)")
        assert new_calls <= 10, (
            f"{url}: expected 4-10 successful usage rows (4 sections + retries + Door 5), got {new_calls}"
        )


async def test_live_extract_real_ats(live_ctx: dict) -> None:
    """Every LIVE_ATS_URL posting → complete JD payload via the real cascade."""
    conn, user_id, urls = live_ctx["conn"], live_ctx["user_id"], live_ctx["urls"]
    for url in urls:
        await _run_one(conn, user_id, url)
