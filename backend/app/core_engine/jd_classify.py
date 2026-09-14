"""Door 0 — URL classification (S6, no Firecrawl port; deterministic regex table).

Routes a posting URL to its entry door and extracts the ATS board ``slug`` and
optional ``job_id``. Matches the canonical mapping
(``docs/components/core_engine/architecture/jd_extractor.md``): Greenhouse and
Lever get Door 1 (ATS public API), Workday/LinkedIn/Indeed and everything else
get Door 2 (JSON-LD → text strip).
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from backend.app.core_engine.jd_schema import DoorRoute

_GREENHOUSE_ID_RE = re.compile(r"/jobs/([^/]+)")
_LEVER_ID_RE = re.compile(r"/postings/([^/]+)")


def classify_url(url: str) -> DoorRoute:
    """Map ``url`` to the entry door + ATS identity. Zero LLM, never raises."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    path = parsed.path or ""

    if host == "boards.greenhouse.io":
        segments = [s for s in path.split("/") if s]
        slug = segments[0] if segments else None
        job_id = None
        match = _GREENHOUSE_ID_RE.search(path)
        if match:
            job_id = match.group(1)
        return DoorRoute(url=url, platform="greenhouse", door=1, slug=slug, job_id=job_id)

    if host.endswith(".greenhouse.io") and "/jobs/" in path:
        slug = host.removesuffix(".greenhouse.io")
        match = _GREENHOUSE_ID_RE.search(path)
        return DoorRoute(url=url, platform="greenhouse", door=1, slug=slug, job_id=match.group(1) if match else None)

    if host == "jobs.lever.co":
        segments = [s for s in path.split("/") if s]
        slug = segments[0] if segments else None
        job_id = segments[1] if len(segments) > 1 else None
        return DoorRoute(url=url, platform="lever", door=1, slug=slug, job_id=job_id)

    if host.endswith("lever.co") and path.startswith("/postings/"):
        segments = [s for s in path.split("/") if s]
        slug = segments[1] if len(segments) > 1 else segments[0]
        match = _LEVER_ID_RE.search(path)
        return DoorRoute(url=url, platform="lever", door=1, slug=slug, job_id=match.group(1) if match else None)

    platform = "generic"
    if host.endswith("myworkdayjobs.com"):
        platform = "workday"
    elif host in {"linkedin.com", "www.linkedin.com"} and path.startswith("/jobs/"):
        platform = "linkedin"
    elif host in {"indeed.com", "www.indeed.com"} and path.startswith("/viewjob"):
        platform = "indeed"
    return DoorRoute(url=url, platform=platform, door=2, slug=None, job_id=None)