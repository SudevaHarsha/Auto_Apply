"""Doors 1-3 (S6): deterministic, zero-LLM JD extraction (provenance port).

Pattern-port provenance note: Door 2 (``extract_json_ld``) and Door 3
(``strip_to_text`` + escalation signals) adapt Firecrawl's
``apps/api/src/lib/extract-jsonld.ts`` and ``apps/api/src/lib/parse/paragraphify.ts``
/``stripToText.ts`` algorithms (doctype-independent ``ld+json`` walk, boilerplate
tag shedding, block-boundary newlines) — AGPL-3.0, own Python implementation,
nothing imports the vendored tree (I9).

Door 1 targets the two public ATS APIs (Greenhouse/Lever) (D30); Door 2 parses
JSON-LD out of any fetched HTML; Door 3 falls back to tag-stripped text so the
token budget (D45) never gets burned on junk prose. 404/transport from Door 1 is
handled by the caller (falls through to Door 2); robots/SSRF (D29/D37) live in
``jd_fetch`` and gate the fetches, not these parsers.
"""

from __future__ import annotations

import html as _html_module
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx

from backend.app.core_engine.errors import FetchFailedError
from backend.app.core_engine.jd_classify import classify_url
from backend.app.core_engine.jd_schema import DoorGaps, DoorRoute

GREENHOUSE_JOBS_URL = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"
GREENHOUSE_JOBS_CONTENT_URL = GREENHOUSE_JOBS_URL + "?content=true"
LEVER_POSTINGS_URL = "https://api.lever.co/v0/postings/{slug}"
LEVER_SINGLE_URL = LEVER_POSTINGS_URL + "/{job_id}"

_BLOCK_TAGS = frozenset(
    {
        "p",
        "div",
        "section",
        "article",
        "li",
        "ul",
        "ol",
        "table",
        "tr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "blockquote",
        "pre",
        "br",
    }
)
# Trim set — tag-based sharpen (D36): shed nav/ads/scripts, keep article/main.
_BOILERPLATE_TAGS = frozenset(
    {
        "script",
        "style",
        "noscript",
        "template",
        "svg",
        "form",
        "nav",
        "header",
        "footer",
        "aside",
        "button",
        "iframe",
        "video",
        "audio",
        "canvas",
        "object",
        "embed",
        "select",
        "input",
        "textarea",
        "label",
        "dialog",
        "figure",
        "figcaption",
    }
)
_KEEP_TAGS: frozenset[str] = frozenset()  # no whitelist needed; trim-set shedding is stricter

_REAL_LIST_RE = re.compile(
    r"\b(careers|job openings|open roles|open positions|current openings|job listings|"
    r"we['’]?re hiring|join our team|see all jobs|careers hub|work with us)\b",
    re.IGNORECASE,
)
_METHODS_MISMATCH_RE = re.compile(
    r"\b(apply via|apply through|email us? your resume|email your r[eé]sum[eé]|"
    r"send your resume|submit your application by email|no online application|"
    r"applications are accepted at|mail your application|apply directly on)\b",
    re.IGNORECASE,
)
_EMPTY_TEXT_THRESHOLD = 200


@dataclass
class DoorResult:
    """One deterministic door's findings. ``html``/``text`` fed forward.

    ``structured`` is the speakable subset (title/company/location/employment/
    salary/…) that Door 4 merges *over* (D40: LLM wins on conflict). ``gaps``
    tells the cascade which critical signals the door left open (D42).
    """

    door: int
    structured: dict[str, Any]
    html: str | None = None
    text: str | None = None
    engine: str = "httpx"

    @property
    def gaps(self) -> DoorGaps:
        return gaps_for(self.structured)


def gaps_for(structured: dict[str, Any]) -> DoorGaps:
    """D42 gap bookkeeping — which critical signals are still missing."""
    missing: list[str] = []
    if not _clean_str(structured.get("title")):
        missing.append("title")
    if not _clean_str(structured.get("company")):
        missing.append("company")
    responsibilities = structured.get("responsibilities") or []
    skills = structured.get("skills") or {}
    required = skills.get("required") or []
    preferred = skills.get("preferred") or []
    if not responsibilities:
        missing.append("responsibilities")
    if not required and not preferred:
        missing.append("skills")
    return DoorGaps(missing_criticals=missing)


def _clean_str(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).replace("\u00a0", " ").strip()
    return re.sub(r"\s+", " ", text)


def _clean_value(stripped: str) -> str | None:
    return stripped if stripped else None


# ---------------------------------------------------------------------------
# Door 1 — ATS public APIs (D30)
# ---------------------------------------------------------------------------


async def door1_greenhouse(
    route: DoorRoute,
    *,
    client: httpx.AsyncClient | None = None,
) -> DoorResult:
    """Greenhouse job board lookup: exact posting via ``/jobs/{job_id}``, else
    the ``?content=true`` list (Finding #1: list matches canonical doc)."""
    if client is None:
        async with httpx.AsyncClient() as own:
            return await _door1_greenhouse(route, client=own)
    return await _door1_greenhouse(route, client=client)


async def _door1_greenhouse(
    route: DoorRoute,
    *,
    client: httpx.AsyncClient,
) -> DoorResult:
    slug = route.slug or ""
    if not slug:
        raise FetchFailedError("greenhouse url missing board slug", details={"url": route.url})
    url = urljoin(GREENHOUSE_JOBS_CONTENT_URL.format(slug=slug), "/")
    job: dict[str, Any] | None = None
    if route.job_id:
        try:
            resp = await client.get(
                f"{GREENHOUSE_JOBS_URL.format(slug=slug)}/{route.job_id}",
                timeout=10.0,
            )
            if resp.status_code == 200:
                candidate = resp.json()
                if isinstance(candidate, dict) and candidate.get("id") is not None:
                    job = candidate
        except (httpx.HTTPError, ValueError):
            pass
    if job is None:
        resp = await client.get(GREENHOUSE_JOBS_CONTENT_URL.format(slug=slug), timeout=10.0)
        if resp.status_code >= 400:
            raise FetchFailedError(
                f"greenhouse board http {resp.status_code}",
                details={"url": url, "status": resp.status_code},
            )
        data = resp.json()
        jobs = data.get("jobs") or []
        if route.job_id:
            job = next((j for j in jobs if str(j.get("id")) == str(route.job_id)), None)
            if job is None:
                job = next((j for j in jobs if route.job_id in str(j.get("absolute_url", ""))), None)
        else:
            job = jobs[0] if jobs else None
    if job is None:
        raise FetchFailedError("no greenhouse job matched", details={"url": route.url})
    return _greenhouse_posting_to_result(job, route)


def _greenhouse_posting_to_result(job: dict[str, Any], route: DoorRoute) -> DoorResult:
    content = job.get("content")
    location = job.get("location") or {}
    location_name = location.get("name") if isinstance(location, dict) else str(location or "")
    structured: dict[str, Any] = {
        "title": _clean_value(_clean_str(job.get("title"))),
        "company": _clean_value(_clean_str(job.get("company_name") or route.slug)),
        "location": _clean_value(_clean_str(location_name)),
        "posted_at": job.get("updated_at"),
        "employment_type": None,
        "seniority": None,
    }
    departments = job.get("departments") or []
    if departments and isinstance(departments, list):
        structured["seniority"] = _clean_value(
            ", ".join(_clean_str(d.get("name")) for d in departments if d.get("name"))
        )
    html = _clean_str(content) or None
    return DoorResult(door=1, structured=structured, html=html)


async def door1_lever(
    route: DoorRoute,
    *,
    client: httpx.AsyncClient | None = None,
) -> DoorResult:
    """Lever posting lookup: exact via ``/v0/postings/{slug}/{job_id}``, else
    the full postings list (mode=json)."""
    if client is None:
        async with httpx.AsyncClient() as own:
            return await _door1_lever(route, client=own)
    return await _door1_lever(route, client=client)


async def _door1_lever(
    route: DoorRoute,
    *,
    client: httpx.AsyncClient,
) -> DoorResult:
    slug = route.slug or ""
    if not slug:
        raise FetchFailedError("lever url missing board slug", details={"url": route.url})
    posting: dict[str, Any] | None = None
    if route.job_id:
        try:
            resp = await client.get(
                LEVER_SINGLE_URL.format(slug=slug, job_id=route.job_id),
                timeout=10.0,
            )
            if resp.status_code in (200, 404):
                data = resp.json() if resp.status_code == 200 else None
                if isinstance(data, dict) and data.get("id"):
                    posting = data
            elif resp.status_code < 400:
                posting = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else None
        except (httpx.HTTPError, ValueError):
            pass
    if posting is None:
        resp = await client.get(LEVER_POSTINGS_URL.format(slug=slug), timeout=10.0)
        if resp.status_code >= 400:
            raise FetchFailedError(
                f"lever api http {resp.status_code}",
                details={"url": route.url, "status": resp.status_code},
            )
        try:
            postings = resp.json()
        except ValueError as exc:
            raise FetchFailedError("lever api returned non-json", details={"url": route.url}) from exc
        if not isinstance(postings, list):
            raise FetchFailedError("lever api returned an unexpected payload", details={"url": route.url})
        if route.job_id:
            posting = next(
                (p for p in postings if str(p.get("id")) == str(route.job_id)),
                None,
            )
        if posting is None:
            posting = postings[0] if postings else None
    if posting is None:
        raise FetchFailedError("no lever posting matched", details={"url": route.url})
    return _lever_posting_to_result(posting, route)


def _lever_posting_to_result(posting: dict[str, Any], route: DoorRoute) -> DoorResult:
    categories = posting.get("categories") or {}
    locations = categories.get("allLocations") or []
    location = categories.get("location") or (", ".join(name for name in locations if name) if locations else None)
    structured: dict[str, Any] = {
        "title": _clean_value(_clean_str(posting.get("text"))),
        "company": _clean_value(_clean_str(posting.get("contactCompanyName") or route.slug)),
        "location": _clean_value(_clean_str(location)),
        "employment_type": _clean_value(_clean_str(categories.get("commitment"))),
        "posted_at": posting.get("createdAt") or posting.get("updatedAt"),
    }
    salary = posting.get("salaryRange")
    if isinstance(salary, dict) and salary.get("interval") != "none":
        structured["salary"] = {
            "min": salary.get("min"),
            "max": salary.get("max"),
            "currency": salary.get("currency"),
            "period": salary.get("interval"),
        }
    lists_html = "".join(
        f"<section>{_html_module.escape(loc.get('text') or '')}</section>"
        for loc in (posting.get("lists") or [])
        if isinstance(loc, dict)
    )
    description_html = _clean_str(posting.get("descriptionHtml")) or _clean_str(posting.get("description"))
    additional = _clean_str(posting.get("additional"))
    html = "<div>" + "".join(part for part in [description_html, lists_html, additional] if part) + "</div>"
    return DoorResult(door=1, structured=structured, html=html or None)


# ---------------------------------------------------------------------------
# Door 2 — JSON-LD (D30): speakable-job-subset parser, no LLM, no models.
# ---------------------------------------------------------------------------


_JSON_LD_SCRIPT_RE = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
    re.DOTALL | re.IGNORECASE,
)


def _ld_list(node: Any) -> list[Any]:
    if isinstance(node, list):
        return node
    if isinstance(node, dict):
        graph = node.get("@graph")
        if isinstance(graph, list):
            return graph
    return [node] if node else []


def _walk_job_postings(node: Any) -> list[dict[str, Any]]:
    jobs: list[dict[str, Any]] = []
    for item in _ld_list(node):
        if not isinstance(item, dict):
            continue
        type_ = item.get("@type")
        if type_ in ("JobPosting", ["JobPosting"]):
            jobs.append(item)
        jobs.extend(_walk_job_postings(item.get("@graph", [])))
        for key in ("hasPart", "mainEntity", "itemListElement"):
            jobs.extend(_walk_job_postings(item.get(key)))
    return jobs


def _first_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, list):
        for entry in value:
            found = _first_text(entry)
            if found:
                return found
        return None
    if isinstance(value, dict):
        if isinstance(value.get("@value"), str):
            return _clean_value(_clean_str(value["@value"]))
        if isinstance(value.get("name"), str):
            return _clean_value(_clean_str(value["name"]))
        return _first_text(value.get("description"))
    if isinstance(value, str):
        return _clean_value(_clean_str(value))
    return str(value) if value else None


def _json_ld_location(job: dict[str, Any]) -> tuple[str | None, str | None]:
    locations = job.get("jobLocation")
    if locations is None:
        return None, None
    labels: list[str] = []
    remote = None
    for loc in _ld_list(locations):
        if not isinstance(loc, dict):
            continue
        loc_type = loc.get("@type")
        if loc_type == "Place":
            address = loc.get("address") or {}
            label = _compose_address(address)
            if label:
                labels.append(label)
            else:
                place_name = _first_text(loc.get("name"))
                if place_name:
                    labels.append(place_name)
        if loc_type == "VirtualLocation" or str(loc.get("name", "")).lower() in {"remote", "telecommute"}:
            remote = "fully-remote"
    return (", ".join(labels) if labels else None), remote


def _compose_address(address: Any) -> str:
    if isinstance(address, str):
        return address
    if isinstance(address, dict):
        parts = [
            address.get("streetAddress"),
            address.get("postalCode"),
            address.get("addressLocality"),
            address.get("addressRegion"),
            address.get("addressCountry"),
        ]
        joined = ", ".join(_clean_str(part) for part in parts if _clean_str(part))
        return joined
    return ""


def _json_ld_salary(job: dict[str, Any]) -> dict[str, Any] | None:
    bs = job.get("baseSalary")
    if bs is None:
        return None
    value = bs.get("value") if isinstance(bs, dict) else None
    currency = bs.get("currency") if isinstance(bs, dict) else None
    period = bs.get("unitText") if isinstance(bs, dict) else None
    if isinstance(value, dict):
        raw_min, raw_max = value.get("minValue"), value.get("maxValue")
        if raw_min is None and raw_max is None:
            raw_min = raw_max = value.get("value")
        try:
            return {
                "min": float(raw_min) if raw_min is not None else None,
                "max": float(raw_max) if raw_max is not None else None,
                "currency": currency,
                "period": period,
            }
        except (TypeError, ValueError):
            return None
    if isinstance(value, int | float):
        return {"min": float(value), "max": float(value), "currency": currency, "period": period}
    if isinstance(value, str):
        match = re.search(r"-?\d+(?:\.\d+)?", value)
        if match:
            return {"min": float(match.group()), "max": float(match.group()), "currency": currency, "period": period}
    return None


def _json_ld_experience(job: dict[str, Any]) -> dict[str, Any] | None:
    yrs = job.get("yearsExperience")
    if not isinstance(yrs, dict):
        return None
    try:
        raw_min = yrs.get("min", yrs.get("minimum"))
        raw_max = yrs.get("max", yrs.get("maximum"))
        return {
            "min_years": float(raw_min) if raw_min is not None else None,
            "max_years": float(raw_max) if raw_max is not None else None,
        }
    except (TypeError, ValueError):
        return None


def extract_json_ld(html: str | bytes) -> dict[str, Any]:
    """Rich-from-HTML Door 2 (ported Firecrawl ``extractJsonLd``): returns the
    speakable-field subset for one ``JobPosting`` node if present (else {})."""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    match = _JSON_LD_SCRIPT_RE.search(html)
    if not match:
        return {}
    try:
        node = json.loads(match.group(1))
    except ValueError:
        return {}
    postings = _walk_job_postings(node)
    if not postings:
        return {}
    job = postings[0]
    structured: dict[str, Any] = {"title": _first_text(job.get("title"))}
    org = job.get("hiringOrganization")
    if isinstance(org, dict):
        structured["company"] = _first_text(org.get("name"))
    location, remote = _json_ld_location(job)
    structured["location"] = location
    structured["remote_policy"] = remote
    structured["employment_type"] = _first_text(job.get("employmentType"))
    structured["experience_range"] = _json_ld_experience(job)
    structured["salary"] = _json_ld_salary(job)
    structured["posted_at"] = _first_text(job.get("datePosted"))
    if job.get("directApply") is True:
        structured["work_auth_visa"] = {"sponsorship": False}
    description = job.get("description")
    if isinstance(description, str):
        structured["_html"] = description
    return {k: v for k, v in structured.items() if v is not None}


# ---------------------------------------------------------------------------
# Door 3 — strip-to-text (D30): boilerplate shedding + block-boundary newlines.
# ---------------------------------------------------------------------------


def strip_to_text(html: str | bytes) -> str:
    """Cleaned readable text, max ~tens of KB — keeps the cascade from burning
    the D45 budget on nav/footer junk and caps cache/API payloads."""
    if not html:
        return ""
    if isinstance(html, bytes):
        html = html.decode("utf-8", errors="replace")
    try:
        return _selectolax_strip(html)
    except ImportError:  # pragma: no cover - selectolax missing, stdlib fallback
        return _stdlib_strip(html)


def _selectolax_strip(html: str) -> str:
    """Decompose boilerplate via selectolax's C DOM, then walk text on the
    serialized body. Works with selectolax 0.4.x (element-only node tree,
    no visible text-node API): ``decompose()`` does the heavy shedding and the
    block-boundary walk is the same ``_extract_text`` algorithm as the
    zero-dependency fallback, so both paths produce identical output (D30)."""
    from selectolax.parser import HTMLParser  # type: ignore[import-not-found]

    parser = HTMLParser(html)
    for tag in _BOILERPLATE_TAGS:
        for node in parser.css(tag):
            node.decompose()
    root = parser.body or parser.root
    if root is None:
        return ""
    serialized = root.html or root.text() or ""
    return _extract_text(serialized)


def _stdlib_strip(html: str) -> str:
    """Zero-dependency fallback so ``import backend.app.core_engine.jd_doors``
    never fails even before ``pip install selectolax`` (D35 keeps CI importable)."""
    return _extract_text(html)


def _extract_text(html: str) -> str:
    """Shared block-boundary text walk (Firecrawl ``paragraphify`` port)."""
    from html.parser import HTMLParser as _PyHTMLParser

    text_buf: list[str] = []

    class _Extractor(_PyHTMLParser):
        def __init__(self) -> None:
            super().__init__(convert_charrefs=True)
            self.block_open = False
            self.skip = False

        def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
            if tag in _BOILERPLATE_TAGS:
                self.skip = True
            elif tag in _BLOCK_TAGS:
                self.block_open = True

        def handle_endtag(self, tag: str) -> None:
            if tag in _BOILERPLATE_TAGS:
                self.skip = False
            elif tag in _BLOCK_TAGS:
                self.block_open = False

        def handle_data(self, data: str) -> None:
            if getattr(self, "skip", False):
                return
            cleaned = re.sub(r"[ \t]+", " ", data)
            if cleaned.strip():
                text_buf.append(("\n" if self.block_open else "") + cleaned)
                text_buf.append("\n")

    parser = _Extractor()
    parser.feed(html)
    joined = "".join(text_buf)
    return re.sub(r"\n{3,}", "\n\n", joined).strip()


# ---------------------------------------------------------------------------
# Gate 3.5 — JS-shell escalation signals (D31)
# ---------------------------------------------------------------------------


def escalation_signal(text: str, url: str, *, html_len: int = 0) -> str | None:
    """D31 signals — which classify a shell to browser-render escalation."""
    lowered = text.lower()
    if len(text.strip()) < _EMPTY_TEXT_THRESHOLD:
        return "Empty"
    if _METHODS_MISMATCH_RE.search(lowered):
        return "Methods mismatch"
    if _REAL_LIST_RE.search(lowered) and html_len < 4_096:
        return "Real list"
    return None  # pragma: no cover - callers treat None as "no escalation"


def looks_like_js_shell(text: str, html: str | bytes) -> bool:
    """D39 Gate 3.5: raw HTML with markup but near-zero usable posting text.

    Mirrors Firecrawl's "JS needed" routing (``#root``/``#app`` mount markers
    plus script-bundle presence). Only fires when httpx really came up empty —
    normal pages never pay the browser cost.
    """
    if len(text.strip()) > 1000:
        return False
    chunk = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else (html or "")
    has_mount_marker = any(
        marker in chunk for marker in ('id="root"', "id='root'", 'id="app"', "id='app'", "<noscript>")
    )
    return bool(has_mount_marker) and len(text.strip()) < 500


def door_route(url: str) -> DoorRoute:
    """Public alias so the extractor and tests need one import site."""
    return classify_url(url)
