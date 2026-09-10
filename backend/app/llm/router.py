"""LLM router core (S4): chain resolution, failover, breaker (D16), exhaustion (D17).

``route_llm_request`` is the single canonical internal entry
(components/llm_router/api_contracts/schema.md:13-32) — consumers import it
directly; there is no HTTP surface (D13). It is a superset: ``job_id``/``step``
(D17) and the opt-in JSON lane ``generate_structured`` / ``json_mode`` /
``output_schema`` (D20), plus an injectable clock and adapter factory
(test-only, default-off).

Semantics (schema.md:36-64 + D16/D19):
- chain = settings ``llm_chain`` ∩ active ``llm_providers`` rows by priority (D15);
  unregistered names are skipped as unavailable.
- per provider: CLOSED -> try; OPEN -> skip until cooldown; HALF_OPEN -> one trial;
  every transition is a guarded UPDATE applied only on rowcount == 1.
- 429 -> OPEN + cooldown = now + max(COOLDOWN_FLOOR, Retry-After ±20% deterministic
  jitter); a 429 never counts toward the N-failure trip counter.
- 500/timeout -> try next; after N consecutive failures the provider trips OPEN.
- invalid key -> marked failed, try next. unavailable -> skip, no breaker change.
- all consumed -> checkpoint marker (when job+step supplied) + audit + raise 503.
"""

from __future__ import annotations

import asyncio
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from backend.app.auth.settings_service import SETTINGS_SPEC_NAMES_WITH_DEFAULTS
from backend.app.db.context import DbContext
from backend.app.db.repositories.auth_repository import AuthRepository
from backend.app.db.repositories.checkpointing_repository import CheckpointingRepository
from backend.app.db.repositories.llm_router_repository import LlmRouterRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository
from backend.app.llm.adapters.base import ProviderAdapter
from backend.app.llm.crypto import DecryptionError, decrypt_provider_key
from backend.app.llm.errors import ProvidersExhaustedError
from backend.app.llm.json_utils import parse_llm_json
from backend.app.llm.registry import is_registered, spec_for

TRIP_THRESHOLD = 3
COOLDOWN_FLOOR_SECONDS = 30.0
DEFAULT_TIMEOUT_SECONDS = 20.0
VALID_PIPELINE_STEPS = frozenset(
    {"jd_extraction", "rubric_generation", "scoring", "optimization", "package_generation"}
)


@dataclass
class LLMResponse:
    content: str
    provider: str
    model: str
    prompt_tokens: int
    completion_tokens: int
    latency_ms: int


def cooldown_for_retry_after(retry_after: float | None, provider_name: str, now: datetime) -> datetime:
    """``now + max(COOLDOWN_FLOOR, retry_after ±20%)`` with deterministic per-provider jitter."""
    seconds = COOLDOWN_FLOOR_SECONDS
    if retry_after is not None:
        jitter = random.Random(provider_name).uniform(0.8, 1.2)
        seconds = max(seconds, retry_after * jitter)
    return now + timedelta(seconds=seconds)


def default_adapter_factory(name: str) -> ProviderAdapter:
    spec = spec_for(name)
    if spec is None:
        raise KeyError(f"unregistered provider: {name}")
    return spec.adapter()


async def _resolve_chain(
    db: DbContext,
    user_id: uuid.UUID,
    provider_chain: list[str] | None,
    repo: LlmRouterRepository,
) -> list[tuple[str, dict[str, Any]]]:
    """Settings names ∩ active provider rows, ordered by priority (D15)."""
    if provider_chain is not None:
        names = provider_chain
    else:
        rows = await AuthRepository(db).get_settings(user_id)
        stored = {key: value for key, value, _ in rows}
        stored_chain = stored.get("llm_chain")
        names = (
            stored_chain
            if isinstance(stored_chain, list) and stored_chain
            else list(SETTINGS_SPEC_NAMES_WITH_DEFAULTS["llm_chain"])
        )
    best_by_name: dict[str, dict[str, Any]] = {}
    for provider in await repo.list_active_providers(user_id):
        best_by_name.setdefault(provider["name"], provider)
    order_index = {name: index for index, name in enumerate(names)}
    chain = [(name, best_by_name[name]) for name in names if name in best_by_name]
    chain.sort(key=lambda item: (item[1]["priority"], order_index[item[0]]))
    return chain


async def _record_failure(
    db: DbContext,
    repo: LlmRouterRepository,
    user_id: uuid.UUID,
    row: dict[str, Any],
    job_id: uuid.UUID | None,
    *,
    error_type: str,
    latency_ms: int = 0,
) -> None:
    await repo.insert_usage(
        user_id,
        provider_id=row["id"],
        job_id=job_id,
        prompt_tokens=0,
        completion_tokens=0,
        latency_ms=latency_ms,
        success=False,
        error_type=error_type,
    )
    await ObservabilityRepository(db).insert_audit(
        action="llm_provider_failed",
        resource_type="provider",
        resource_id=row["id"],
        details={"provider": row["name"], "error_type": error_type},
    )


async def _try_decrypt_key(row: dict[str, Any]) -> str | None:
    blob = row.get("api_key_encrypted")
    if not blob:
        return None
    return decrypt_provider_key(blob)


async def _handle_count_failure(
    db: DbContext,
    repo: LlmRouterRepository,
    user_id: uuid.UUID,
    name: str,
    *,
    observed_state: str,
    error_type: str,
    now: datetime,
) -> None:
    """Increment the consecutive-failure counter; trip OPEN at the threshold (D16)."""
    breaker = await repo.get_breaker(user_id, name)
    if breaker is None:
        await repo.ensure_breaker(user_id, name)
        current = 0
    else:
        current = breaker["failure_count"]
    await repo.increment_failure(user_id, name, current_failure_count=current, last_failure_at=now)
    if current + 1 >= TRIP_THRESHOLD:
        await repo.trip_circuit(
            user_id,
            name,
            failure_count_delta=0,
            cooldown_expires_at=now + timedelta(seconds=COOLDOWN_FLOOR_SECONDS),
            last_failure_at=now,
            observed_state=observed_state,
        )


async def _handle_breakers(
    db: DbContext, repo: LlmRouterRepository, user_id: uuid.UUID, name: str, now: datetime
) -> tuple[bool, bool]:
    """Return (proceed, trial_claimed). Missing row = implicitly CLOSED."""
    breaker = await repo.get_breaker(user_id, name)
    if breaker is None:
        return True, False
    state = breaker["state"]
    if state == "CLOSED":
        return True, False
    if state == "OPEN":
        cooldown = breaker.get("cooldown_expires_at")
        if cooldown is not None and cooldown > now:
            return False, False
        claimed = await repo.claim_trial(user_id, name, now=now)
        return claimed, claimed
    claimed = await repo.claim_trial(user_id, name, now=now)
    return claimed, claimed


async def _exhaust(
    db: DbContext,
    repo: LlmRouterRepository,
    user_id: uuid.UUID,
    *,
    job_id: uuid.UUID | None,
    step: str | None,
    providers_consumed: list[str],
    error_message: str,
) -> None:
    await ObservabilityRepository(db).insert_audit(
        action="all_providers_exhausted",
        resource_type="system",
        resource_id=None,
        details={"providers": providers_consumed, "error_message": error_message},
    )
    if job_id is not None and step in VALID_PIPELINE_STEPS:
        await CheckpointingRepository(db).insert(
            "checkpoints",
            {
                "user_id": user_id,
                "job_id": job_id,
                "step": step,
                "pipeline_state": {
                    "llm_all_providers_exhausted": True,
                    "failed_providers": providers_consumed,
                    "error_message": error_message,
                },
            },
        )


async def route_llm_request(
    conn: psycopg.AsyncConnection,
    *,
    user_id: uuid.UUID,
    prompt: str,
    system_message: str | None = None,
    provider_chain: list[str] | None = None,
    job_id: uuid.UUID | None = None,
    step: str | None = None,
    json_mode: bool = False,
    output_schema: dict[str, Any] | None = None,
    adapter_factory: Callable[[str], ProviderAdapter] | None = None,
    now: datetime | None = None,
) -> LLMResponse:
    now = now or datetime.now(UTC)
    builder = adapter_factory if adapter_factory is not None else default_adapter_factory
    async with DbContext(conn, user_id).transaction() as db:
        repo = LlmRouterRepository(db)
        chain = await _resolve_chain(db, user_id, list(provider_chain) if provider_chain else None, repo)
        consumed: list[str] = []
        for name, row in chain:
            if not is_registered(name):
                continue
            proceed, trial = await _handle_breakers(db, repo, user_id, name, now)
            if not proceed:
                continue
            api_key: str | None = None
            if row.get("api_key_encrypted"):
                try:
                    api_key = await _try_decrypt_key(row)
                except DecryptionError:
                    await _record_failure(db, repo, user_id, row, job_id, error_type="invalid_key")
                    continue
            adapter = builder(name)
            response = await asyncio.to_thread(
                adapter.chat,
                prompt=prompt,
                system_message=system_message,
                model=row["model"],
                base_url=row["base_url"],
                api_key=api_key,
                json_mode=json_mode,
                output_schema=output_schema,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
            consumed.append(name)
            if response.status == "ok":
                if trial:
                    await repo.reset_circuit(user_id, name, observed_state="HALF_OPEN")
                await repo.insert_usage(
                    user_id,
                    provider_id=row["id"],
                    job_id=job_id,
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    latency_ms=response.latency_ms,
                    success=True,
                )
                return LLMResponse(
                    content=response.content or "",
                    provider=name,
                    model=response.model or row["model"],
                    prompt_tokens=response.prompt_tokens,
                    completion_tokens=response.completion_tokens,
                    latency_ms=response.latency_ms,
                )
            error_type = response.error_type or ("timeout" if response.status == "timeout" else "server_error")
            if response.status == "unavailable":
                await _record_failure(
                    db, repo, user_id, row, job_id, error_type="unavailable", latency_ms=response.latency_ms
                )
                continue
            if error_type == "rate_limited" or response.status_code == 429:
                await repo.ensure_breaker(user_id, name)
                await repo.trip_circuit(
                    user_id,
                    name,
                    failure_count_delta=0,
                    cooldown_expires_at=cooldown_for_retry_after(response.retry_after, name, now),
                    last_failure_at=now,
                    observed_state="HALF_OPEN" if trial else "CLOSED",
                )
            else:
                await _handle_count_failure(
                    db,
                    repo,
                    user_id,
                    name,
                    observed_state="HALF_OPEN" if trial else "CLOSED",
                    error_type=error_type,
                    now=now,
                )
            await _record_failure(db, repo, user_id, row, job_id, error_type=error_type, latency_ms=response.latency_ms)
        error_message = f"all LLM providers exhausted: {', '.join(consumed) or 'none resolved'}"
        await _exhaust(
            db, repo, user_id, job_id=job_id, step=step, providers_consumed=consumed, error_message=error_message
        )
    raise ProvidersExhaustedError(error_message)


async def generate_structured(
    conn: psycopg.AsyncConnection,
    *,
    user_id: uuid.UUID,
    prompt: str,
    system_message: str | None,
    output_model: Any,
    provider_chain: list[str] | None = None,
    job_id: uuid.UUID | None = None,
    step: str | None = None,
    max_repairs: int = 1,
    adapter_factory: Callable[[str], ProviderAdapter] | None = None,
    now: datetime | None = None,
) -> Any:
    """Internal typed superset (D20): enforce JSON + pydantic validation.

    Output-shape failures count as normal failed attempts (usage + audit) and get
    at most ``max_repairs`` repair prompt(s) to the same provider, then the chain
    advances — the circuit is **never tripped** by shape failures (only 429/5xx/
    timeout do). Returns the validated ``output_model`` instance.
    """
    now = now or datetime.now(UTC)
    schema = output_model.model_json_schema()
    builder = adapter_factory if adapter_factory is not None else default_adapter_factory
    async with DbContext(conn, user_id).transaction() as db:
        repo = LlmRouterRepository(db)
        chain = await _resolve_chain(db, user_id, list(provider_chain) if provider_chain else None, repo)
        consumed: list[str] = []
        for name, row in chain:
            if not is_registered(name):
                continue
            proceed, trial = await _handle_breakers(db, repo, user_id, name, now)
            if not proceed:
                continue
            if row.get("api_key_encrypted"):
                try:
                    api_key = await _try_decrypt_key(row)
                except DecryptionError:
                    await _record_failure(db, repo, user_id, row, job_id, error_type="invalid_key")
                    continue
            else:
                api_key = None
            adapter = builder(name)
            consumed.append(name)
            repairs_used = 0
            call_prompt = prompt
            while True:
                response = await asyncio.to_thread(
                    adapter.chat,
                    prompt=call_prompt,
                    system_message=system_message,
                    model=row["model"],
                    base_url=row["base_url"],
                    api_key=api_key,
                    json_mode=True,
                    output_schema=schema,
                    timeout=DEFAULT_TIMEOUT_SECONDS,
                )
                if response.status == "ok":
                    parsed = parse_llm_json(response.content or "")
                    if parsed is not None:
                        try:
                            validated = output_model.model_validate(parsed)
                        except Exception:
                            validated = None
                    else:
                        validated = None
                    if validated is not None:
                        if trial:
                            await repo.reset_circuit(user_id, name, observed_state="HALF_OPEN")
                        await repo.insert_usage(
                            user_id,
                            provider_id=row["id"],
                            job_id=job_id,
                            prompt_tokens=response.prompt_tokens,
                            completion_tokens=response.completion_tokens,
                            latency_ms=response.latency_ms,
                            success=True,
                        )
                        return validated
                    error_type = "schema_mismatch" if parsed is not None else "invalid_json"
                    await _record_failure(
                        db,
                        repo,
                        user_id,
                        row,
                        job_id,
                        error_type=error_type,
                        latency_ms=response.latency_ms,
                    )
                    if repairs_used >= max_repairs:
                        break
                    repairs_used += 1
                    call_prompt = (
                        prompt
                        + "\n\nYour previous output was not valid JSON. Return ONLY valid JSON "
                        + "matching the requested schema, with no prose and no code fences."
                    )
                    continue
                if response.status == "unavailable":
                    await _record_failure(
                        db,
                        repo,
                        user_id,
                        row,
                        job_id,
                        error_type="unavailable",
                        latency_ms=response.latency_ms,
                    )
                    break
                error_type = response.error_type or ("timeout" if response.status == "timeout" else "server_error")
                if error_type == "rate_limited" or response.status_code == 429:
                    await repo.ensure_breaker(user_id, name)
                    await repo.trip_circuit(
                        user_id,
                        name,
                        failure_count_delta=0,
                        cooldown_expires_at=cooldown_for_retry_after(response.retry_after, name, now),
                        last_failure_at=now,
                        observed_state="HALF_OPEN" if trial else "CLOSED",
                    )
                else:
                    await _handle_count_failure(
                        db,
                        repo,
                        user_id,
                        name,
                        observed_state="HALF_OPEN" if trial else "CLOSED",
                        error_type=error_type,
                        now=now,
                    )
                await _record_failure(
                    db, repo, user_id, row, job_id, error_type=error_type, latency_ms=response.latency_ms
                )
                break
        error_message = f"all LLM providers exhausted: {', '.join(consumed) or 'none resolved'}"
        await _exhaust(
            db, repo, user_id, job_id=job_id, step=step, providers_consumed=consumed, error_message=error_message
        )
    raise ProvidersExhaustedError(error_message)
