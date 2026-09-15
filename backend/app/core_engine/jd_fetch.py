"""JD fetcher (S6, D29/D33/D37) — httpx default fetch with Firecrawl-derived safety.

Pattern-port provenance note: the fetch-safety layer adapts the *algorithms* of
Firecrawl's ``apps/api/src/scrapeURL/engines/utils/safeFetch.ts`` (``isIPPrivate``,
hop-by-hop ``resolveRedirects`` validation, header hygiene) and
``apps/api/src/lib/robots-txt.ts`` (24h per-host robots cache) — AGPL-3.0. This is
our own Python implementation; nothing imports or runs the vendored tree (I9).

Guarantees the cascade's Door 2/3 fetches are safe against untrusted posting
content: private/loopback/link-local/reserved targets are rejected before any
request, every redirect hop is re-validated, a neutral UA is sent (so bot-sniffing
ATS keep serving), and robots.txt compliance is strictly opt-in (``respect_robots``,
D37) — never blocking a user-requested snapshot by default.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import urllib.robotparser
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from backend.app.core_engine.errors import FetchFailedError

_DEFAULT_HEADERS = {
    "User-Agent": "autoapply-agent/0.1 (+manual job-snapshot fetcher)",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
}

FETCH_TIMEOUT_SECONDS = 10.0
MAX_REDIRECTS = 5
ROBOTS_CACHE_TTL_SECONDS = 86_400  # Firecrawl lib/robots-txt.ts fetchRobotsTxt 24h maxAge
ROBOTS_FETCH_TIMEOUT_SECONDS = 8.0
_ROBOTS_UA = "autoapply-agent/0.1"


@dataclass
class FetchedResult:
    """Canonical fetch outcome (``FetchedResult`` mirrors safeFetch's metadata shape)."""

    url: str
    status_code: int
    headers: dict[str, str]
    body: bytes
    robots_allowed: bool | None
    ssrf_checked: bool
    engine: str = "httpx"
    extra: dict[str, Any] = field(default_factory=dict)


_NAT64_WELL_KNOWN = ipaddress.IPv6Network("64:ff9b::/96")  # RFC 6052 global translation prefix


def _host_is_private(host: str) -> bool:
    """Block private/loopback/link-local/reserved/multicast/unspecified targets.

    Port of Firecrawl ``isIPPrivate`` (safeFetch.ts): one stdlib ``ipaddress``
    call for literals; unresolved hostnames are conservatively blocked too.

    RFC 6052 aware: addresses in the well-known ``64:ff9b::/96`` NAT64 prefix
    (produced for v4-only hosts by DNS64 resolvers) carry an embedded IPv4 in
    their low 32 bits. That embedded address is classified with the **same**
    rules instead of the suffixed v6 range, so public IPv4 behind NAT64 is
    fetchable while ``64:ff9b::<private/loopback/...>`` stays blocked. The
    local-use ``64:ff9b:1::/48`` prefix (RFC 8215) is *not* special-cased and
    remains blocked by ``is_reserved``.
    """
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    if ip.version == 6 and ip in _NAT64_WELL_KNOWN:
        ip = ipaddress.ip_address(int(ip) & 0xFFFFFFFF)
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
        or not ip.is_global
    )


async def _resolve_ip_candidates(host: str) -> list[str]:
    """All resolved IPs for a hostname (DNS happens on the worker thread)."""
    if not host:
        return []
    try:
        infos = await asyncio.to_thread(socket.getaddrinfo, host, None)
    except OSError:
        return []
    return [str(info[4][0]) for info in infos]


async def _ssrf_allows(url: str) -> bool:
    """SSRF posture check for one hop — literal IP or full DNS resolution scan."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False
    host = parsed.hostname or ""
    if not host:
        return False
    if _host_is_private(host):
        return False
    if host.replace(".", "").isdigit() or ":" in host:
        # numeric literal already classified above; IPv6 literal handled by ipaddress
        return True
    candidates = await _resolve_ip_candidates(host)
    if not candidates:
        return False
    return not any(_host_is_private(candidate) for candidate in candidates)


async def _fetch_and_check_robots(
    url: str,
    *,
    client: httpx.AsyncClient,
    fetch_timeout: float,
) -> bool | None:
    """``robots_allows`` with a 24h per-host cache (Firecrawl ``lib/robots-txt.ts``).

    Returns True/False when a robots.txt is reachable and parseable, None when it
    cannot be determined (fail-open — robots never blocks a user snapshot on a
    resolver outage).
    """
    host = urlparse(url).hostname or ""
    if not host:
        return None
    now = datetime.now(UTC)
    cached = _ROBOTS_CACHE.get(host)
    if cached is not None and (now - cached[0]).total_seconds() < ROBOTS_CACHE_TTL_SECONDS:
        hit_parser = cached[1]
        return None if hit_parser is None else not hit_parser.can_fetch(_ROBOTS_UA, url)

    resolved_parser: urllib.robotparser.RobotFileParser | None = None
    try:
        robots_url = f"https://{host}/robots.txt"
        resp = await client.get(
            robots_url,
            headers=_DEFAULT_HEADERS,
            timeout=fetch_timeout,
            follow_redirects=True,
        )
        if resp.status_code < 400 and resp.text:
            parsed_parser = urllib.robotparser.RobotFileParser()
            parsed_parser.set_url(robots_url)
            parsed_parser.parse(resp.text.splitlines())
            resolved_parser = parsed_parser
    except (httpx.HTTPError, OSError, ValueError):
        resolved_parser = None
    _ROBOTS_CACHE[host] = (now, resolved_parser)
    return None if resolved_parser is None else not resolved_parser.can_fetch(_ROBOTS_UA, url)


async def robots_allows(
    url: str,
    *,
    max_age_seconds: int = ROBOTS_CACHE_TTL_SECONDS,
    client: httpx.AsyncClient | None = None,
    fetch_timeout: float = ROBOTS_FETCH_TIMEOUT_SECONDS,
) -> bool | None:
    """Public opt-in robots check (D37): config gate off → callers never call this."""
    if max_age_seconds != ROBOTS_CACHE_TTL_SECONDS:
        _ROBOTS_CACHE.pop(urlparse(url).hostname or "", None)
    async with _maybe_own_client(client) as own:
        return await _fetch_and_check_robots(url, client=own, fetch_timeout=fetch_timeout)


async def fetch_http(
    url: str,
    *,
    fetch_timeout: float = FETCH_TIMEOUT_SECONDS,
    follow_redirects: bool = True,
    ssrf_guard: bool = True,
    respect_robots: bool = False,
    headers: dict[str, str] | None = None,
    client: httpx.AsyncClient | None = None,
) -> FetchedResult:
    """Default cascader fetcher (D29): httpx GET with per-hop SSRF revalidation.

    Redirect hops are walked manually (mirrors safeFetch's ``resolveRedirects``)
    so a clean 302 → ``http://169.254.169.254/…`` is blocked *before* the second
    request; the canonical final URL feeds ``content_hash`` (D28). 404s return
    normally in ``FetchedResult.status_code`` (freshness input); transport and
    SSRF/robots blocks raise :class:`FetchFailedError`.
    """
    merged_headers = {**_DEFAULT_HEADERS, **(headers or {})}
    own_client = False
    if client is None:
        client = httpx.AsyncClient(follow_redirects=False, timeout=fetch_timeout, headers=merged_headers)
        own_client = True

    current_url = url
    robots_decision: bool | None = None
    try:
        if respect_robots:
            robots_decision = await _fetch_and_check_robots(url, client=client, fetch_timeout=fetch_timeout)
            if robots_decision is True:
                raise FetchFailedError(
                    "robots.txt disallows this path",
                    details={"url": url, "path": urlparse(url).path},
                )
        for _hop in range(max(1, MAX_REDIRECTS + 1)):
            if ssrf_guard and not await _ssrf_allows(current_url):
                raise FetchFailedError(
                    "URL resolves to a private/loopback/link-local target (SSRF guard)",
                    details={"url": current_url},
                )
            resp = await client.get(current_url, headers=merged_headers, timeout=fetch_timeout)
            if resp.status_code in (301, 302, 303, 307, 308):
                location = resp.headers.get("location")
                if not location:
                    return FetchedResult(
                        url=str(resp.url),
                        status_code=int(resp.status_code),
                        headers=dict(resp.headers),
                        body=resp.content,
                        robots_allowed=robots_decision,
                        ssrf_checked=ssrf_guard,
                    )
                current_url = str(resp.url.join(location))
                continue
            return FetchedResult(
                url=str(resp.url),
                status_code=int(resp.status_code),
                headers=dict(resp.headers),
                body=resp.content,
                robots_allowed=robots_decision,
                ssrf_checked=ssrf_guard,
                engine="httpx",
            )
        raise FetchFailedError("too many redirects", details={"url": url})
    except httpx.HTTPError as exc:
        raise FetchFailedError(f"fetch failed: {exc}", details={"url": url}) from exc
    finally:
        if own_client:
            await client.aclose()


_ROBOTS_CACHE: dict[str, tuple[datetime, urllib.robotparser.RobotFileParser | None]] = {}


@asynccontextmanager
async def _maybe_own_client(
    client: httpx.AsyncClient | None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Yield caller-provided client or create a short-lived own client."""
    if client is not None:
        yield client
        return
    own = httpx.AsyncClient(follow_redirects=True, timeout=ROBOTS_FETCH_TIMEOUT_SECONDS)
    try:
        yield own
    finally:
        await own.aclose()
