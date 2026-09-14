"""S9 discovery helpers (S6-shipped primitives, no network in CI).

Pattern-port provenance: adapted from Firecrawl
``apps/api/src/lib/search/search-query-builder.ts`` (``buildSearchQuery``),
``apps/api/src/search/v2/ddgsearch.ts`` (DDG HTML fallback), and
``apps/api/src/lib/threat-protection/request.ts`` (URL safety filter) — AGPL-3.0,
own Python implementations. S9 wires these into actual discovery; nothing here
touches the network in the CI-gated suite.
"""

from __future__ import annotations

import html as _html
import math
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

_SITE_CATEGORIES: frozenset[str] = frozenset({"github", "research", "pdf"})
_DDG_RESULT_RE = re.compile(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>')

_PRIVATE_HOST_RE = re.compile(
    r"^(127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[0-1])\.|169\.254\.|0\.|100\.(6[4-9]|[7-9]\d)\b)",
    re.IGNORECASE,
)
_MALWARE_DOMAINS: frozenset[str] = frozenset()


@dataclass
class SearchResult:
    url: str
    title: str


def build_search_query(
    query: str,
    *,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
    categories: list[str] | None = None,
) -> str:
    """Port of ``buildSearchQuery``: prepend ``site:`` for github/research/pdf
    categories; append ``site:`` / ``-site:`` per domain filter."""
    q = query
    if categories:
        for category in categories:
            if category.lower() in _SITE_CATEGORIES:
                q = f"site:{category}.com {q}"
    for domain in include_domains or []:
        q = f"{q} site:{domain}"
    for domain in exclude_domains or []:
        q = f"{q} -site:{domain}"
    return q.strip()


def overfetch_limit(limit: int) -> int:
    """Firecrawl ``num_results_buffer = floor(limit * 2)``."""
    return math.floor(int(limit) * 2)


async def ddg_search_fallback(
    query: str,
    *,
    limit: int = 20,
    client: Any | None = None,
) -> list[SearchResult]:
    """DuckDuckGo HTML fallback parser. ``client`` injected in tests; production
    uses an ``httpx.AsyncClient`` from the caller's pool."""
    url = "https://html.duckduckgo.com/html/?q=" + _url_quote(query)
    headers = {"User-Agent": "autoapply-agent/0.1"}
    if client is None:
        import httpx

        async with httpx.AsyncClient() as own:
            return await _ddg_fetch(own, url, headers, limit)
    return await _ddg_fetch(client, url, headers, limit)


async def _ddg_fetch(client, url: str, headers: dict[str, str], limit: int) -> list[SearchResult]:
    resp = await client.get(url, headers=headers, timeout=10.0)
    if resp.status_code == 202:
        starred = {**headers, "User-Agent": "Mozilla/5.0 (compatible; JobSearch/1.0)"}
        resp = await client.get(url, headers=starred, timeout=10.0)
    if resp.status_code >= 400:
        return []
    html = resp.text
    results: list[SearchResult] = []
    for href, title_html in _DDG_RESULT_RE.findall(html):
        title = _html.unescape(re.sub(r"<[^>]+>", "", title_html)).strip()
        results.append(SearchResult(url=_html.unescape(href), title=title))
        if len(results) >= limit:
            break
    return results


def _url_quote(query: str) -> str:
    from urllib.parse import quote

    return quote(query, safe="")


async def check_urls_against_threat_policy(urls: list[str]) -> list[str]:
    """Port of ``checkUrlsAgainstThreatPolicy``: https-only, private-IP reject,
    malware-domain denylist. Returns the allowed subset."""
    allowed: list[str] = []
    for url in urls:
        if not url.lower().startswith("https://"):
            continue
        host = (urlparse(url).hostname or "").lower()
        if not host or _PRIVATE_HOST_RE.search(host):
            continue
        if host in _MALWARE_DOMAINS:
            continue
        allowed.append(url)
    return allowed