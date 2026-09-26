"""Browser-render fetcher (S6 default Door 2/3 fetcher, D29/D33/D37/D39, provenance port).

Pattern-port provenance note: adapted from Firecrawl ``apps/api/src/scrapeURL/engines/playwright/index.ts``
(browser-use is gated behind an env flag; page blocked under ``page.route`` for
third-party + tracking/stats/ads domains; ``domcontentloaded`` wait) — AGPL-3.0,
our own Python/Playwright implementation, importable even when Playwright is not
installed (lazy import, D35: ``jd_render`` env flag + ``jd-render`` extra gate it).

This is the browser-first default fetch for the extraction cascade: it replaces
the Gate 3.5 JS-shell heuristic with a direct render, so SPA/JS-shell postings
(Workday, SmartRecruiters, Cisco careers, …) are fetched with the content the
page actually shows. It reuses the httpx engine's SSRF (D33) and robots (D37)
guards before navigating, mirrors the ``FetchedResult`` shape so Door 2's
JSON-LD parser needs zero changes, and raises :class:`FetchFailedError` for
SSRF/robots blocks just like the httpx engine does.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any
from urllib.parse import urlparse

from backend.app.core_engine.errors import FetchFailedError
from backend.app.core_engine.jd_fetch import FetchedResult, robots_allows, ssrf_allows

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
    ssrf_guard: bool = True,
    respect_robots: bool = False,
    playwright: Any | None = None,
) -> FetchedResult:
    """Render ``url`` headlessly and return the post-render HTML as ``FetchedResult``.

    SSRF (D33) and robots (D37) guards run **before** launching the browser, on the
    same code path the httpx engine uses — a blocked target raises
    :class:`FetchFailedError` with the same shape, never opening a browser for it.
    A redirect landing on a non-public target is also rejected after navigation
    (``page.url`` re-checked through the same guard). The browser never ignores
    robots when the caller opts in (``respect_robots``, default False like httpx).

    ``playwright`` is injected in tests; in production it is imported lazily from
    the ``jd-render`` extra. This engine reuses the httpx engine's
    ``FetchedResult`` shape so Door 2's JSON-LD parser needs zero changes.

    Windows: Playwright's driver spawns Chromium via asyncio subprocess
    transports, which a ``SelectorEventLoop`` cannot provide (the app's db
    policy) — so on win32 the browser always runs on a dedicated worker thread
    with its own ``ProactorEventLoop``; every other platform runs inline.
    """
    if not jd_render_enabled():
        raise RuntimeError("browser render gate (JD_RENDER_AVAILABLE) is closed")

    if respect_robots:
        robots_decision = await robots_allows(url)
        if robots_decision is True:
            raise FetchFailedError(
                "robots.txt disallows this path",
                details={"url": url, "path": urlparse(url).path},
            )
    if ssrf_guard and not await ssrf_allows(url):
        raise FetchFailedError(
            "URL resolves to a private/loopback/link-local target (SSRF guard)",
            details={"url": url},
        )

    if sys.platform == "win32":
        return await asyncio.to_thread(_run_browser_worker, url, timeout_ms, ssrf_guard)
    return await _browser_impl(url, timeout_ms, ssrf_guard=ssrf_guard)


def _run_browser_worker(url: str, timeout_ms: int, ssrf_guard: bool) -> FetchedResult:
    """Run the render on a Proactor loop in this thread (win32 subprocess support).

    ``ProactorEventLoop()`` is constructed directly so the process-wide event-loop
    policy (SelectorEventLoop, set for psycopg async) is never mutated.
    """
    loop = asyncio.ProactorEventLoop()  # type: ignore[attr-defined]
    try:
        return loop.run_until_complete(_browser_impl(url, timeout_ms, ssrf_guard=ssrf_guard))
    finally:
        loop.close()


async def _browser_impl(url: str, timeout_ms: int, *, ssrf_guard: bool) -> FetchedResult:
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
            if ssrf_guard and not await ssrf_allows(page.url):
                raise FetchFailedError(
                    "redirected to a private/loopback/link-local target (SSRF guard)",
                    details={"url": page.url},
                )
            await page.wait_for_load_state("networkidle", timeout=timeout_ms)
            html = await page.content()
            return FetchedResult(
                url=page.url,
                status_code=int(response.status) if response else 200,
                headers=dict(await response.all_headers()) if response else {},
                body=html.encode("utf-8", errors="replace"),
                robots_allowed=None,
                ssrf_checked=ssrf_guard,
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
