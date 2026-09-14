"""Browser-render fetcher (S6 Gate 3.5 escalations, D31/D35, provenance port).

Pattern-port provenance note: adapted from Firecrawl ``apps/api/src/scrapeURL/engines/playwright/index.ts``
(browser-use is gated behind an env flag; page blocked under ``page.route`` for
third-party + tracking/stats/ads domains; ``domcontentloaded`` wait) — AGPL-3.0,
our own Python/Playwright implementation, importable even when Playwright is not
installed (lazy import, D35: ``jd_render`` env flag + ``jd-render`` extra gate it).

Used only when Door 3 text extraction yields methods mismatch/the-real-list/Empty
signals (D31) and the ``JD_RENDER_AVAILABLE`` env flag is set; rollover to this
engine re-runs Door 2/3 on the rendered HTML with ``fetch_engine="browser"``.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from backend.app.core_engine.jd_fetch import FetchedResult

JD_RENDER_ENV = "JD_RENDER_AVAILABLE"  # truthy → playwright render path allowed

# Third-party / ads / tracking substrings — ported from Firecrawl's browser routes.
_BLOCKED_RESOURCE_SUBSTRINGS = (
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "adservice.google.",
    "hotjar.com",
    "segment.io",
    "amplitude.com",
    "mixpanel.com",
    "scorecardresearch.com",
    "facebook.net",
    "connect.facebook.net",
    "beacons.gtm",
)

_BLOCKED_RESOURCE_TYPES = ("image", "media", "font", "stylesheet", "texttrack")


def jd_render_enabled() -> bool:
    """Config gate for the browser engine (D35) — False without flags/env set."""
    return os.getenv(JD_RENDER_ENV, "").lower() in {"1", "true", "yes"}


async def fetch_browser(
    url: str,
    *,
    timeout_ms: int = 15_000,
    playwright: Any | None = None,
) -> FetchedResult:
    """Render ``url`` headlessly and return the post-render HTML as ``FetchedResult``.

    ``playwright`` is injected in tests; in production it is imported lazily from
    the ``jd-render`` extra. Robots policy (D37) is respected only when the
    calling context opted in — extraction up there repeats the same SSRF guard
    before this is reachable, and this engine reuses the httpx engine's
    ``FetchedResult`` shape so Door 2's JSON-LD parser needs zero changes.

    Windows: Playwright's driver spawns Chromium via asyncio subprocess
    transports, which a ``SelectorEventLoop`` cannot provide (the app's db
    policy) — so on win32 the browser always runs on a dedicated worker thread
    with its own ``ProactorEventLoop``; every other platform runs inline.
    """
    if not jd_render_enabled():
        raise RuntimeError("browser render gate (JD_RENDER_AVAILABLE) is closed")

    if sys.platform == "win32":
        return await asyncio.to_thread(_run_browser_worker, url, timeout_ms)
    return await _browser_impl(url, timeout_ms)


def _run_browser_worker(url: str, timeout_ms: int) -> FetchedResult:
    """Run the render on a Proactor loop in this thread (win32 subprocess support).

    ``ProactorEventLoop()`` is constructed directly so the process-wide event-loop
    policy (SelectorEventLoop, set for psycopg async) is never mutated.
    """
    loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
    try:
        return loop.run_until_complete(_browser_impl(url, timeout_ms))
    finally:
        loop.close()


async def _browser_impl(url: str, timeout_ms: int) -> FetchedResult:
    try:
        from playwright.async_api import async_playwright  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - only when extra missing
        raise RuntimeError("playwright not installed (jd-render extra)") from exc

    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            page = await browser.new_page()
            await _block_noisy_resources(page)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            html = await page.content()
            return FetchedResult(
                url=page.url,
                status_code=int(response.status) if response else 200,
                headers=dict(await response.all_headers()) if response else {},
                body=html.encode("utf-8", errors="replace"),
                robots_allowed=None,
                ssrf_checked=True,
                engine="browser",
            )
        finally:
            await browser.close()


async def _block_noisy_resources(page: Any) -> None:
    """Ported from Firecrawl's browser route: shed third-party/tracking payloads."""
    async def _handle(route: Any) -> None:
        request = route.request
        url = request.url.lower()
        if request.resource_type in _BLOCKED_RESOURCE_TYPES or any(
            substring in url for substring in _BLOCKED_RESOURCE_SUBSTRINGS
        ):
            await route.abort()
        elif url.startswith("http"):
            await route.continue_()

    await page.route("**/*", _handle)