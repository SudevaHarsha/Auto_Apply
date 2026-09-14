"""JD extractor cascade (S6) — the main service layer for job-posting extraction.

Mandatory 4-section Door 4 (D34/D40/D41), freshness gating, D27/D45 budget
accounting, shared cache fast-path (I4), and browser-escalation (D39) live here.
Audits via ``ObservabilityRepository``; persistence via ``CoreEngineRepository``.
No HTTP routes — ``backend_api`` (S14) wires them.

Guardrails ported from Firecrawl's ``transformers/llmExtract.ts`` algorithms:
``trimToTokenLimit`` (char pre-trim → ``tiktoken`` exact), the heuristic
prompt-injection scan (chunk + overlap + fail-open, port of
``checkForPromptInjection``), and the refusal-phrase scan (port of
``LLMRefusalError`` detection). AGPL-3.0 provenance noted per function; own
Python implementation — nothing runs the vendored tree (I9).
"""

from __future__ import annotations

import hashlib
import logging
import math
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg

from backend.app.core_engine.errors import (
    ExtractionBudgetExceededError,
    FetchFailedError,
    JobNotFoundError,
    NotAPostingError,
    StructuredJDValidationError,
)
from backend.app.core_engine.jd_classify import classify_url
from backend.app.core_engine.jd_doors import (
    DoorResult,
    door1_greenhouse,
    door1_lever,
    extract_json_ld,
    gaps_for,
    looks_like_js_shell,
    strip_to_text,
)
from backend.app.core_engine.jd_fetch import FetchedResult, fetch_http
from backend.app.core_engine.jd_prompts import (
    build_door5_prompt,
    build_door5_system,
    build_section_prompt,
    build_section_system,
)
from backend.app.core_engine.jd_schema import (
    CURRENT_SCHEMA_VERSION,
    SECTION_MODELS,
    DoorRoute,
    StructuredJD,
    merge_over,
)
from backend.app.db.context import DbContext
from backend.app.db.repositories.core_engine_repository import CoreEngineRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository
from backend.app.llm.errors import ProvidersExhaustedError
from backend.app.llm.json_utils import parse_llm_json
from backend.app.llm.router import route_llm_request

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# S6 constants (D36)
# ---------------------------------------------------------------------------

_MAX_CHARS_PER_TOKEN: float = 5.0  # port-plan firecrawl char-per-token heuristic
_FALLBACK_CHARS_PER_TOKEN: float = 2.8
_SECTION_MAX_INPUT_TOKENS: int = 12_000
_INJECTION_OVERLAP: int = 2048
_INJECTION_CHUNK: int = 32_000
_OUTPUT_HEADROOM_TOKENS: int = 2048
_JD_TOKEN_BUDGET_ENV = "JD_EXTRACTION_TOKEN_BUDGET"
_DEFAULT_TOKEN_BUDGET: int = 45_000
_MAX_CALLS: int = 5  # D27 hard loop cap (4 Door-4 + 0–1 Door-5)
_JD_CACHE_ENV = "JD_CACHE_ENABLED"

_INJECTION_PATTERNS: tuple[str, ...] = (
    "ignore all previous instructions",
    "ignore previous instructions",
    "system prompt",
    "you are now",
    "disregard instructions",
    "do not follow the instructions",
    "override instructions",
)

_REFUSAL_PATTERNS: tuple[str, ...] = (
    "i am not a job posting",
    "i cannot fulfill this request",
    "i am unable to",
    "this is not a job posting",
    "as an ai",
    "as a language model",
)

_DOOR4_SECTIONS: tuple[str, ...] = ("header_core", "responsibilities", "skills", "good_to_have")


# ---------------------------------------------------------------------------
# Ported helpers — token estimation (firecrawl ``trimToTokenLimit``)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TrimResult:
    """Pre-trimmed text + the token estimate used for D45 budgeting."""

    text: str
    char_count: int
    estimated_tokens: int
    warning: str | None = None


_TOKENIZER: Any = None


def _get_tokenizer() -> Any:
    """Lazily import ``tiktoken`` when the ``jd-render`` extra installed it."""
    global _TOKENIZER  # noqa: PLW0603
    if _TOKENIZER is not None:
        return _TOKENIZER
    try:  # pragma: no cover – offline CI may lack tiktoken
        import tiktoken  # type: ignore[import-not-found]

        _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _TOKENIZER = None
    return _TOKENIZER


def _estimate_tokens(text: str, chars_per_token: float = _MAX_CHARS_PER_TOKEN) -> int:
    return max(1, math.ceil(len(text) / chars_per_token))


def trim_to_token_limit(
    text: str,
    max_tokens: int,
    *,
    chars_per_token: float = _MAX_CHARS_PER_TOKEN,
) -> TrimResult:
    """Char pre-trim fast-path + optional ``tiktoken`` exact trim (port of Firecrawl).

    The ``estimated_tokens`` return is what D45 consumes for budgeting — conservative
    when tiktoken is absent, exact when it is present.
    """
    if not text:
        return TrimResult(text="", char_count=0, estimated_tokens=0)

    fast_cap_chars = int(max_tokens * chars_per_token)
    pretrimmed = text[:fast_cap_chars]
    tok = _get_tokenizer()
    if tok is not None:
        tokens = tok.encode(pretrimmed)
        if len(tokens) <= max_tokens:
            return TrimResult(
                text=pretrimmed,
                char_count=len(pretrimmed),
                estimated_tokens=len(tokens),
            )
        decoded = tok.decode(tokens[:max_tokens])
        return TrimResult(
            text=decoded,
            char_count=len(decoded),
            estimated_tokens=max_tokens,
            warning=f"tiktoken-trimmed {len(tokens)}→{max_tokens}",
        )
    return TrimResult(
        text=pretrimmed,
        char_count=len(pretrimmed),
        estimated_tokens=_estimate_tokens(pretrimmed, chars_per_token),
        warning="fallback char-per-token (tiktoken unavailable)" if fast_cap_chars < len(text) else None,
    )


# ---------------------------------------------------------------------------
# Ported helpers — refusal scan (firecrawl ``LLMRefusalError`` heuristic)
# ---------------------------------------------------------------------------


def _is_refusal(content: str) -> bool:
    lower = content.lower()
    return any(phrase in lower for phrase in _REFUSAL_PATTERNS)


# ---------------------------------------------------------------------------
# Ported helpers — prompt-injection heuristic (firecrawl ``checkForPromptInjection``)
# ---------------------------------------------------------------------------


def check_for_prompt_injection(text: str) -> bool:
    """Overlap-aware chunk scan — matches firecrawl's ``_INJECTION_OVERLAP`` safety contract."""
    if not text:
        return False
    scan_text = text.lower()
    for start in range(0, len(scan_text), _INJECTION_CHUNK - _INJECTION_OVERLAP):
        chunk = scan_text[start : start + _INJECTION_CHUNK]
        if any(pattern in chunk for pattern in _INJECTION_PATTERNS):
            return True
    return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def _token_budget_env() -> int:
    raw = os.getenv(_JD_TOKEN_BUDGET_ENV, "")
    try:
        return int(raw) if raw else _DEFAULT_TOKEN_BUDGET
    except (ValueError, TypeError):
        return _DEFAULT_TOKEN_BUDGET


def _cache_enabled() -> bool:
    return os.getenv(_JD_CACHE_ENV, "1").lower() not in {"0", "false", "no"}


def content_hash(url: str, body: bytes) -> str:
    """D28: ``sha256(final_url + fetched_body_bytes)``."""
    return hashlib.sha256(url.encode("utf-8") + body).hexdigest()


def is_plausible_posting(
    payload: dict[str, Any],
    *,
    raw_text: str,
    jsonld_found: bool,
) -> bool:
    """D43 gate — reject career-hub/list pages and empty shells before any persist."""
    if jsonld_found:
        return True
    skills = payload.get("skills") or {}
    responsibilities = payload.get("responsibilities") or []
    return bool(responsibilities or skills.get("required") or skills.get("preferred"))


# ---------------------------------------------------------------------------
# Budget (D27 count cap + D45 token accumulator)
# ---------------------------------------------------------------------------


@dataclass
class _BudgetTracker:
    cap: int = _MAX_CALLS
    token_budget: int = field(default_factory=_token_budget_env)
    headroom: int = _OUTPUT_HEADROOM_TOKENS
    used_tokens: int = 0
    call_count: int = 0

    def fits(self, planned_input: int) -> bool:
        return self.used_tokens + planned_input + self.headroom <= self.token_budget

    def guard_plan(self, planned_input: int) -> None:
        if not self.fits(planned_input):
            raise ExtractionBudgetExceededError(
                "pre-call token budget would be exceeded",
                details={
                    "used": self.used_tokens,
                    "planned": planned_input,
                    "headroom": self.headroom,
                    "budget": self.token_budget,
                },
            )

    def consume_call(self) -> None:
        if self.call_count >= self.cap:
            raise ExtractionBudgetExceededError(
                "extraction call cap reached",
                details={"calls": self.call_count, "cap": self.cap},
            )
        self.call_count += 1

    def accrue(self, prompt_tokens: int, completion_tokens: int) -> None:
        self.used_tokens += prompt_tokens + completion_tokens
        if self.used_tokens + self.headroom > self.token_budget:
            raise ExtractionBudgetExceededError(
                "post-call token budget exceeded",
                details={"used": self.used_tokens, "budget": self.token_budget},
            )


# ---------------------------------------------------------------------------
# Default fetch / render injection seams
# ---------------------------------------------------------------------------


async def default_fetch(
    url: str,
    *,
    ssrf_guard: bool = True,
    respect_robots: bool = False,
    headers: dict[str, str] | None = None,
    client: Any | None = None,
) -> FetchedResult:
    return await fetch_http(
        url,
        ssrf_guard=ssrf_guard,
        respect_robots=respect_robots,
        headers=headers,
        client=client,
    )


async def default_render(url: str, *, playwright: Any | None = None) -> FetchedResult | None:
    try:
        from backend.app.core_engine.jd_fetch_browser import fetch_browser, jd_render_enabled

        if not jd_render_enabled():
            return None
        return await fetch_browser(url, playwright=playwright)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Service layer dataclasses (§9)
# ---------------------------------------------------------------------------


@dataclass
class JobExtraction:
    job: dict[str, Any]
    snapshot_id: uuid.UUID | None
    payload: dict[str, Any]
    raw_text: str | None
    extracted_via_door: int
    cache_hit: bool
    fetch_engine: str


@dataclass
class FreshnessResult:
    state: str
    snapshot_id: uuid.UUID | None = None
    hash_changed: bool = False


@dataclass
class JobSummary:
    id: uuid.UUID
    title: str | None
    company: str | None
    url: str | None
    platform: str | None
    status: str | None
    score: int | None
    freshness_state: str | None
    created_at: datetime | None


@dataclass
class JobDetail:
    id: uuid.UUID
    title: str | None
    company: str | None
    url: str | None
    platform: str | None
    status: str | None
    score: int | None
    freshness_state: str | None
    raw_text: str | None
    payload: dict[str, Any] | None
    snapshot_id: uuid.UUID | None
    content_hash: str | None
    created_at: datetime | None


# ---------------------------------------------------------------------------
# Room-4 per-section runner
# ---------------------------------------------------------------------------


async def _run_door4_section(
    section: str,
    *,
    text: str,
    accumulator: dict[str, Any],
    budget: _BudgetTracker,
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    adapter_factory: Callable[[str], Any] | None,
    iso_now: str,
) -> tuple[dict[str, Any] | None, str | None]:
    """One focused ``route_llm_request`` call (S5 pattern, ``extraction._call_llm_for_section``)."""
    model = SECTION_MODELS[section]
    system = build_section_system(section, iso_now)
    trimmed = trim_to_token_limit(text, _SECTION_MAX_INPUT_TOKENS)
    prompt = build_section_prompt(section, trimmed.text)
    planned = trimmed.estimated_tokens + _estimate_tokens(system)

    budget.guard_plan(planned)
    budget.consume_call()

    try:
        resp = await route_llm_request(
            conn,
            user_id=user_id,
            prompt=prompt,
            system_message=system,
            json_mode=True,
            output_schema=model.model_json_schema(),
            adapter_factory=adapter_factory,
        )
    except ProvidersExhaustedError:
        budget.accrue(planned, 0)
        return None, f"{section}: router_exhausted"
    except Exception:  # noqa: BLE001
        budget.accrue(planned, 0)
        return None, f"{section}: router_error"

    budget.accrue(resp.prompt_tokens or 0, resp.completion_tokens or 0)

    if _is_refusal(resp.content or ""):
        return None, f"{section}: refused"

    parsed = parse_llm_json(resp.content or "")
    if parsed is None:
        return None, f"{section}: parse_error"

    parsed_stripped = {k: v for k, v in parsed.items() if k != "_meta"}
    try:
        obj = model(**parsed_stripped)
    except Exception:
        return None, f"{section}: schema_error"

    section_dict = obj.model_dump(mode="json")
    merge_over(accumulator, section_dict)
    return section_dict, None


# ---------------------------------------------------------------------------
# Repository helpers
# ---------------------------------------------------------------------------


async def _get_or_create_for_user(
    repo: CoreEngineRepository,
    user_id: uuid.UUID,
    route: DoorRoute,
    source: str,
    *,
    title: str = "",
    company: str = "",
) -> tuple[dict[str, Any], bool]:
    """``UNIQUE(user_id, url)`` get-or-create with conflict-safe INSERT."""
    url = route.url
    existing = await repo.find_job_by_url(user_id, url)
    if existing is not None:
        return existing, False
    await repo.insert(
        "jobs",
        {
            "user_id": str(user_id),
            "title": title or "(unextracted)",
            "company": company or "(unextracted)",
            "url": url,
            "platform": route.platform,
            "source": source,
            "status": "discovered",
        },
    )
    job = await repo.find_job_by_url(user_id, url)
    assert job is not None, "jobs row vanished after insert"
    return job, True


async def _audit(
    obs_repo: ObservabilityRepository,
    *,
    action: str,
    resource_type: str,
    resource_id: uuid.UUID | str | None,
    details: dict[str, Any] | None = None,
) -> None:
    await obs_repo.insert_audit(
        action=action,
        resource_type=resource_type,
        resource_id=str(resource_id) if resource_id is not None else None,
        details=details or {},
    )


# ---------------------------------------------------------------------------
# Public service layer (§9) — extract_job is the main entry point
# ---------------------------------------------------------------------------


async def extract_job(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    url: str,
    *,
    fetch: Callable[..., Any] | None = None,
    render: Callable[..., Any] | None = None,
    source: str = "manual",
    adapter_factory: Callable[[str], Any] | None = None,
    now: datetime | None = None,
) -> JobExtraction:
    """Full S6 cascade: classify → doors 1-3 (+ render) → mandatory 4-section Door 4 →
    Door 5 gap-fill → plausibility gate → persist + audits."""
    now = now or datetime.now(UTC)
    iso_now = now.isoformat()
    fetch_call = fetch or default_fetch
    render_call = render or default_render

    route = classify_url(url)

    async with DbContext(conn, user_id).transaction() as db:
        core_repo = CoreEngineRepository(db)
        obs_repo = ObservabilityRepository(db)

        # URL-keyed cache fast-path (I4): "no new fetch for user 2"
        if _cache_enabled():
            cached = await core_repo.find_snapshot_by_source_url(route.url)
            if cached is not None:
                payload: dict[str, Any] = cached["payload"] if isinstance(cached.get("payload"), dict) else {}
                job, created = await _get_or_create_for_user(
                    core_repo,
                    user_id,
                    route,
                    source,
                    title=payload.get("title") or "",
                    company=payload.get("company") or "",
                )
                if job.get("current_snapshot_id") != cached["id"]:
                    await core_repo.apply_snapshot(
                        job_id=job["id"],
                        snapshot_id=cached["id"],
                        content_hash=cached["content_hash"],
                    )
                if created:
                    await _audit(
                        obs_repo,
                        action="job_discovered",
                        resource_type="job",
                        resource_id=job["id"],
                        details={"url": route.url, "cache_hit": True},
                    )
                return JobExtraction(
                    job=job,
                    snapshot_id=cached["id"],
                    payload=payload,
                    raw_text=cached.get("raw_text"),
                    extracted_via_door=payload.get("_meta", {}).get("extracted_via_door", 4),
                    cache_hit=True,
                    fetch_engine=payload.get("_meta", {}).get("fetch_engine", "httpx"),
                )

        # --- non-cache path: run the cascade ---
        accumulator: dict[str, Any] = {}
        html: str | None = None
        hash_body: bytes | None = None
        engine = "httpx"
        final_url = route.url
        jsonld_found = False

        # Door 1 — ATS public API
        if route.door == 1:
            async with httpx.AsyncClient() as ats_client:
                try:
                    door1: DoorResult
                    if route.platform == "greenhouse":
                        door1 = await door1_greenhouse(route, client=ats_client)
                    else:
                        door1 = await door1_lever(route, client=ats_client)
                    for key, value in door1.structured.items():
                        if value is not None:
                            accumulator[key] = value
                    html = door1.html
                    if html is not None:
                        hash_body = html.encode("utf-8", errors="replace")
                    engine = door1.engine
                except FetchFailedError:
                    pass

        # Doors 2–3 — fetch + JSON-LD + text strip
        need_fetch = html is None or gaps_for(accumulator).has_criticals
        fetched: FetchedResult | None = None
        if need_fetch:
            fetched = await fetch_call(route.url)
            if fetched.status_code == 404:
                raise JobNotFoundError("posting not found", details={"url": route.url})
            if fetched.status_code >= 400:
                raise FetchFailedError(
                    "page fetch failed",
                    details={"url": route.url, "status": fetched.status_code},
                )
            final_url = fetched.url
            decoded_body = fetched.body.decode("utf-8", errors="replace")
            html = decoded_body
            hash_body = fetched.body
            jsonld_dict = extract_json_ld(fetched.body)
            jsonld_found = bool(jsonld_dict)
            for key, value in jsonld_dict.items():
                if key == "_html":
                    if not html or len(decoded_body) < len(str(value)):
                        html = str(value)
                    continue
                # D30 cascade: Door 2 fills gaps only — never clobbers Door 1's structured values
                if value is not None and accumulator.get(key) is None:
                    accumulator[key] = value

        cleaned_text = strip_to_text(html or "")

        # Gate 3.5 — JS-shell browser escalation (D39/D31)
        if html and looks_like_js_shell(cleaned_text, html):
            try:
                rendered = await render_call(final_url)
                if rendered is not None and rendered.body:
                    rendered_text = strip_to_text(rendered.body)
                    if len(rendered_text.strip()) > len(cleaned_text.strip()):
                        cleaned_text = rendered_text
                        html = rendered.body.decode("utf-8", errors="replace")
                        engine = "browser"
                        final_url = rendered.url
                        rendered_jsonld = extract_json_ld(rendered.body)
                        if rendered_jsonld:
                            jsonld_found = True
                            for key, value in rendered_jsonld.items():
                                if key != "_html" and value is not None and accumulator.get(key) is None:
                                    accumulator[key] = value
                        hash_body = rendered.body
            except Exception:
                pass  # escalation best-effort; proceed with httpx text

        # --- Door 4 (mandatory, D40/D41) ---
        budget = _BudgetTracker()
        gaps_recorded: list[str] = []
        injection_flagged = check_for_prompt_injection(cleaned_text)

        if not injection_flagged and cleaned_text:
            for section in _DOOR4_SECTIONS:
                _, gap = await _run_door4_section(
                    section,
                    text=cleaned_text,
                    accumulator=accumulator,
                    budget=budget,
                    conn=conn,
                    user_id=user_id,
                    adapter_factory=adapter_factory,
                    iso_now=iso_now,
                )
                if gap is not None:
                    gaps_recorded.append(gap)
        else:
            gaps_recorded.append("prompt_injection_flagged" if injection_flagged else "empty_text")

        # Door 5 — targeted 0-1 gap-fill (skips, never raises, when budget gone — D45)
        remaining_gaps = gaps_for(accumulator)
        if remaining_gaps.has_criticals and cleaned_text and not injection_flagged:
            door5_system = build_door5_system(iso_now)
            trimmed = trim_to_token_limit(cleaned_text, _SECTION_MAX_INPUT_TOKENS)
            prompt = build_door5_prompt(trimmed.text, remaining_gaps.missing_criticals)
            planned = trimmed.estimated_tokens + _estimate_tokens(door5_system)
            if not budget.fits(planned):
                gaps_recorded.append("door5_budget_skip")
            else:
                budget.guard_plan(planned)
                budget.consume_call()
                try:
                    resp = await route_llm_request(
                        conn,
                        user_id=user_id,
                        prompt=prompt,
                        system_message=door5_system,
                        json_mode=True,
                        adapter_factory=adapter_factory,
                    )
                    budget.accrue(resp.prompt_tokens or 0, resp.completion_tokens or 0)
                    if not _is_refusal(resp.content or ""):
                        parsed_door5 = parse_llm_json(resp.content or "")
                        if parsed_door5 is not None:
                            stripped = {k: v for k, v in parsed_door5.items() if k != "_meta"}
                            merge_over(accumulator, stripped)
                except ProvidersExhaustedError:
                    gaps_recorded.append("door5: router_exhausted")
                except Exception:
                    gaps_recorded.append("door5: router_error")

        # --- Gate D43 (plausibility) ---
        extracted_via_door = 4 if budget.call_count > 0 else (3 if html else (2 if fetched else 1))
        raw_text = cleaned_text
        final_hash_body = hash_body or b""
        final_url_hash = final_url

        payload = dict(accumulator)
        payload["_meta"] = {
            "schema_version": CURRENT_SCHEMA_VERSION,
            "extracted_via_door": extracted_via_door,
            "source_url": final_url,
            "fetch_engine": engine,
            "extraction_tokens": budget.used_tokens,
            "confidence": None,
        }

        try:
            StructuredJD(**payload)
        except Exception as exc:
            raise StructuredJDValidationError(
                "extracted payload failed schema validation",
                details={"errors": str(exc)},
            ) from exc

        if not is_plausible_posting(payload, raw_text=raw_text, jsonld_found=jsonld_found):
            raise NotAPostingError(
                "not a job posting (D43 gate)",
                details={"url": route.url, "jsonld_found": jsonld_found},
            )

        # --- Persist (I1/I4) ---
        h = content_hash(final_url_hash, final_hash_body)
        snapshot_id = await core_repo.upsert_snapshot(h, payload=payload, raw_text=raw_text)
        job, created = await _get_or_create_for_user(
            core_repo,
            user_id,
            route,
            source,
            title=payload.get("title") or "",
            company=payload.get("company") or "",
        )
        await core_repo.apply_snapshot(
            job_id=job["id"],
            snapshot_id=snapshot_id,
            content_hash=h,
        )

        if created:
            await _audit(
                obs_repo,
                action="job_discovered",
                resource_type="job",
                resource_id=job["id"],
                details={"url": route.url, "platform": route.platform},
            )
        await _audit(
            obs_repo,
            action="job_extracted",
            resource_type="job",
            resource_id=job["id"],
            details={
                "snapshot_id": str(snapshot_id),
                "extracted_via_door": extracted_via_door,
                "cache_hit": False,
            },
        )

        return JobExtraction(
            job=job,
            snapshot_id=snapshot_id,
            payload=payload,
            raw_text=raw_text,
            extracted_via_door=extracted_via_door,
            cache_hit=False,
            fetch_engine=engine,
        )


# ---------------------------------------------------------------------------
# refresh_job — I2: hash compare + version bump + 404→stale
# ---------------------------------------------------------------------------


async def refresh_job(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    *,
    fetch: Callable[..., Any] | None = None,
    render: Callable[..., Any] | None = None,
    adapter_factory: Callable[[str], Any] | None = None,
    now: datetime | None = None,
) -> FreshnessResult:
    """Re-fetch the posting at ``jobs.url``; version-bump when content changed (I2)."""
    now = now or datetime.now(UTC)
    async with DbContext(conn, user_id).transaction() as db:
        core_repo = CoreEngineRepository(db)
        obs_repo = ObservabilityRepository(db)

        job = await core_repo.get_job_detail(user_id, job_id)
        if job is None:
            raise JobNotFoundError("job not found", details={"job_id": str(job_id)})

        url = job["url"]
        fetch_call = fetch or default_fetch

        try:
            fetched = await fetch_call(url)
        except Exception:
            await core_repo.mark_freshness(job_id, "stale")
            await _audit(
                obs_repo,
                action="job_freshness_changed",
                resource_type="job",
                resource_id=job_id,
                details={"state": "stale", "reason": "fetch_failed"},
            )
            return FreshnessResult(state="stale")

        if fetched.status_code == 404 or fetched.status_code >= 400:
            await core_repo.mark_freshness(job_id, "stale")
            await _audit(
                obs_repo,
                action="job_freshness_changed",
                resource_type="job",
                resource_id=job_id,
                details={"state": "stale", "reason": f"http_{fetched.status_code}"},
            )
            return FreshnessResult(state="stale")

        new_hash = content_hash(fetched.url, fetched.body)
        if new_hash == job.get("content_hash"):
            await core_repo.touch_last_fetched(job_id)
            return FreshnessResult(state="fresh")

        result = await extract_job(
            conn,
            user_id,
            url,
            fetch=fetch,
            render=render,
            adapter_factory=adapter_factory,
            now=now,
        )
        await _audit(
            obs_repo,
            action="job_freshness_changed",
            resource_type="job",
            resource_id=job_id,
            details={"state": "fresh", "old_hash": job.get("content_hash"), "new_hash": new_hash},
        )
        return FreshnessResult(state="fresh", snapshot_id=result.snapshot_id, hash_changed=True)


# ---------------------------------------------------------------------------
# §9 ops
# ---------------------------------------------------------------------------


async def get_or_create_job(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    url: str,
    *,
    title: str = "",
    company: str = "",
    platform: str = "generic",
    source: str = "manual",
) -> dict[str, Any]:
    route = DoorRoute(url=url, platform=platform, door=2)
    async with DbContext(conn, user_id).transaction() as db:
        repo = CoreEngineRepository(db)
        job, _created = await _get_or_create_for_user(repo, user_id, route, source, title=title, company=company)
        return job


async def list_jobs(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    *,
    status: str | None = None,
    platform: str | None = None,
    limit: int = 20,
    cursor: str | None = None,
) -> tuple[list[JobSummary], str | None]:
    """Keyset-paginated job summaries (§9), no payload, no raw_text."""
    async with DbContext(conn, user_id).transaction() as db:
        repo = CoreEngineRepository(db)
        rows, next_cursor = await repo.list_jobs(
            user_id,
            status=status,
            platform=platform,
            limit=limit,
            cursor=cursor,
        )
        summaries = [
            JobSummary(
                id=r["id"],
                title=r["title"],
                company=r["company"],
                url=r["url"],
                platform=r["platform"],
                status=r["status"],
                score=r["score"],
                freshness_state=r["freshness_state"],
                created_at=r["created_at"],
            )
            for r in rows
        ]
        return summaries, next_cursor


async def get_job(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> JobDetail | None:
    async with DbContext(conn, user_id).transaction() as db:
        repo = CoreEngineRepository(db)
        row = await repo.get_job_detail(user_id, job_id)
        if row is None:
            return None
        return JobDetail(
            id=row["id"],
            title=row["title"],
            company=row["company"],
            url=row["url"],
            platform=row["platform"],
            status=row["status"],
            score=row["score"],
            freshness_state=row["freshness_state"],
            raw_text=row["raw_text"],
            payload=row["payload"],
            snapshot_id=row["current_snapshot_id"],
            content_hash=row["content_hash"],
            created_at=row["created_at"],
        )


async def update_job_status(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    status: str,
) -> bool:
    async with DbContext(conn, user_id).transaction() as db:
        repo = CoreEngineRepository(db)
        return await repo.update_job_status(user_id, job_id, status)


async def delete_job(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> bool:
    async with DbContext(conn, user_id).transaction() as db:
        repo = CoreEngineRepository(db)
        obs_repo = ObservabilityRepository(db)
        job = await repo.get_job_detail(user_id, job_id)
        if job is None:
            return False
        await repo.delete_job(user_id, job_id)
        await _audit(obs_repo, action="job_rejected", resource_type="job", resource_id=job_id)
        return True


async def freshness_state(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> str | None:
    async with DbContext(conn, user_id).transaction() as db:
        repo = CoreEngineRepository(db)
        job = await repo.get_job_detail(user_id, job_id)
        return job["freshness_state"] if job else None


async def freshness_for_package(
    conn: psycopg.AsyncConnection,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
) -> dict[str, Any]:
    async with DbContext(conn, user_id).transaction() as db:
        repo = CoreEngineRepository(db)
        job = await repo.get_job_detail(user_id, job_id)
        if job is None:
            return {"state": "stale", "blocked": True}
        if job.get("freshness_state") == "expired":
            return {"state": "expired", "blocked": True}
        if job.get("freshness_state") == "stale":
            return {"state": "stale", "blocked": True}
        last_fetched = job.get("last_fetched_at")
        if last_fetched is None:
            return {"state": "stale", "blocked": True}
        now = datetime.now(UTC)
        age = now - last_fetched.replace(tzinfo=UTC) if last_fetched.tzinfo is None else now - last_fetched
        if age <= timedelta(hours=6):
            return {"state": "ok(<6h)", "blocked": False}
        return {"state": job.get("freshness_state", "stale"), "blocked": True}
