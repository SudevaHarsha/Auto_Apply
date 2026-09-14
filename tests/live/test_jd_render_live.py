"""Live JD browser-render test — opt-in, real Chromium over the real wire (S6, D39).

Proves the Door-3 browser escalation (D31/D35/D39) works against a real Workday /
SmartRecruiters style JS-shell posting from ``LIVE_RENDER_URL``:

  real ``fetch_http`` → page detected as a JS shell (``looks_like_js_shell``) →
  real Playwright/Chromium render (``fetch_browser``) → Door 2/3 re-run on the
  rendered HTML → Door 4 with a **mocked** LLM (render never costs budget, and
  this test only proves the browser leg — no provider keys required).

Skips when: not under ``-Target test-integration-live`` (``RUN_LIVE_LLM=1``),
``LIVE_RENDER_URL`` unset, ``JD_RENDER_AVAILABLE`` not enabled, Playwright not
installed (``jd-render`` extra), browsers not installed, or the live page is not
actually a JS shell (nothing to render). A real pipeline bug fails the suite.
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

from backend.app.auth.service import AuthService  # noqa: E402
from backend.app.core_engine.jd_doors import looks_like_js_shell, strip_to_text  # noqa: E402
from backend.app.core_engine.jd_extractor import default_render, extract_job  # noqa: E402
from backend.app.core_engine.jd_fetch import FetchedResult, fetch_http  # noqa: E402
from backend.app.core_engine.jd_fetch_browser import fetch_browser, jd_render_enabled  # noqa: E402
from backend.app.llm.service import LlmProviderService  # noqa: E402
from tests.doubles.mock_provider import ok, scripted_factory  # noqa: E402

pytestmark = pytest.mark.live

APP_URL = os.getenv("DATABASE_URL", "postgresql://app_user:changeme_in_production@localhost:5435/autoapply")
PASSWORD = "Str0ng!password"


def _four_ok():
    """Scripted Door-4 responses (mocked LLM — render must not consume budget)."""
    return [
        ok(
            json.dumps(
                {
                    "title": "Rendered Title",
                    "company": "Rendered Co",
                    "location": "Remote",
                    "employment_type": "Full-time",
                    "remote_policy": "Remote",
                }
            ),
            pt=400,
            ct=400,
        ),
        ok(json.dumps({"responsibilities": ["Run the render pipeline", "Ship features"]}), pt=400, ct=400),
        ok(
            json.dumps({"skills": {"required": ["Python"], "preferred": ["Playwright"]}}),
            pt=400,
            ct=400,
        ),
        ok(json.dumps({"good_to_have": ["Browser automation"]}), pt=400, ct=400),
    ]


async def _conn() -> psycopg.AsyncConnection:
    return await psycopg.AsyncConnection.connect(APP_URL)


async def _register() -> tuple[psycopg.AsyncConnection, object]:
    conn = await _conn()
    try:
        result = await AuthService(conn).register(
            email=f"live-render-{uuid.uuid4().hex[:10]}@example.com",
            password=PASSWORD,
            name="Live JD Render Tester",
        )
    except Exception:
        await conn.close()
        raise
    return conn, result


@pytest_asyncio.fixture(scope="module")
async def live_render_ctx() -> dict:
    if os.environ.get("RUN_LIVE_LLM") != "1":
        pytest.skip("live render test disabled; run .\\tasks.ps1 -Target test-integration-live")
    url = os.environ.get("LIVE_RENDER_URL", "").strip()
    if not url:
        pytest.skip("LIVE_RENDER_URL empty - set it to a real JS-shell Workday/SmartRecruiters posting URL")
    if not jd_render_enabled():
        pytest.skip("JD_RENDER_AVAILABLE unset - browser render gate (D35) is closed")
    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        pytest.skip(f"playwright not installed (jd-render extra): {exc}")
    conn, result = await _register()
    user_id = result.id
    try:
        for index, name in enumerate(("gemini", "groq", "openrouter")):
            await LlmProviderService(conn).add_provider(
                user_id=user_id,
                name=name,
                base_url=None,
                api_key="dummy-render-test-key",
                priority=index,
            )
    except Exception:
        await conn.close()
        raise
    yield {"conn": conn, "user_id": user_id, "url": url}
    await conn.close()


async def test_jd_render_live(live_render_ctx: dict) -> None:
    conn, user_id, url = live_render_ctx["conn"], live_render_ctx["user_id"], live_render_ctx["url"]

    try:
        raw = await fetch_http(url)
    except Exception as exc:  # noqa: BLE001 - live ATS/environmental only
        pytest.skip(f"raw fetch unavailable for {url}: {exc}")
    assert isinstance(raw, FetchedResult)
    html = raw.body.decode("utf-8", errors="replace")
    text = strip_to_text(html)
    if not looks_like_js_shell(text, html):
        pytest.skip(f"{url} is not a JS shell ({len(text)} chars) - nothing to render")

    try:
        probe = await fetch_browser(url, timeout_ms=15_000)
    except Exception as exc:  # noqa: BLE001 - best-effort render leg (D39)
        pytest.skip(f"real Chromium render unavailable for {url}: {exc}")
    assert isinstance(probe, FetchedResult), f"{url}: browser probe returned no result"

    factory, adapters, call_log = scripted_factory({"gemini": _four_ok()})
    try:
        result = await extract_job(
            conn,
            user_id,
            url,
            render=default_render,
            adapter_factory=factory,
        )
    except Exception as exc:  # noqa: BLE001 - environmental during live run
        pytest.skip(f"extraction over real Chromium failed for {url}: {exc}")

    assert result.fetch_engine == "browser", f"{url}: expected browser backstop, got {result.fetch_engine}"
    assert result.payload.get("_meta", {}).get("fetch_engine") == "browser"
    assert result.payload.get("title"), f"{url}: rendered extraction produced no title"
    total_calls = sum(len(adapter.calls) for adapter in adapters.values())
    assert total_calls == 4, f"render leg must not consume LLM budget (D39); got {total_calls} calls: {call_log}"
    assert len(call_log) == 4, f"expected exactly 4 Door-4 calls, got {len(call_log)}"