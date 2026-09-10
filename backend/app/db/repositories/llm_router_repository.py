"""llm_router repository — owns llm_providers, provider_usage, rate_limit_state.

All reads/writes are RLS-scoped by the owning ``DbContext`` (``SET LOCAL
app.user_id``). Every circuit-breaker transition is a **guarded UPDATE** applied
only on ``rowcount == 1`` (D16) so concurrent requests can never double-issue the
HALF_OPEN trial or lose consecutive-failure increments.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

from backend.app.db.repositories.base import BaseRepository

_PROVIDER_COLUMNS = ("id", "name", "base_url", "model", "api_key_encrypted", "is_active", "priority", "created_at")

TRIAL_WINDOW_SECONDS = 60.0

_SELECT_PROVIDER = (
    "SELECT id, name, base_url, model, api_key_encrypted, is_active, priority, created_at FROM llm_providers"
)


def _row_to_dict(row: tuple[Any, ...]) -> dict[str, Any]:
    return dict(zip(_PROVIDER_COLUMNS, row, strict=False))


class LlmRouterRepository(BaseRepository):
    """llm_router owns provider configuration, usage accounting and rate-limit state."""

    owns = frozenset({"llm_providers", "provider_usage", "rate_limit_state"})

    # ------------------------------------------------------------ providers
    async def list_providers(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await (await self.db.execute(f"{_SELECT_PROVIDER} ORDER BY priority, created_at")).fetchall()
        return [_row_to_dict(r) for r in rows]

    async def list_active_providers(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        rows = await (
            await self.db.execute(f"{_SELECT_PROVIDER} WHERE is_active ORDER BY priority, created_at")
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    async def get_provider(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> dict[str, Any] | None:
        row = await (
            await self.db.execute(
                f"{_SELECT_PROVIDER} WHERE id = %s AND user_id = %s",
                (str(provider_id), str(user_id)),
            )
        ).fetchone()
        return _row_to_dict(row) if row else None

    async def count_providers_by_name(self, user_id: uuid.UUID, name: str) -> int:
        """Case-insensitive name collision check (B2; no DB UNIQUE on llm_providers)."""
        n = await self.db.fetch_scalar(
            "SELECT count(*) FROM llm_providers WHERE lower(name) = lower(%s) AND user_id = %s",
            (name, str(user_id)),
        )
        return int(n or 0)

    async def create_provider(
        self,
        user_id: uuid.UUID,
        *,
        name: str,
        base_url: str,
        model: str,
        api_key_encrypted: str | None,
        priority: int,
        is_active: bool = True,
    ) -> dict[str, Any]:
        provider_id = await self.insert(
            "llm_providers",
            {
                "user_id": user_id,
                "name": name,
                "base_url": base_url,
                "model": model,
                "api_key_encrypted": api_key_encrypted,
                "priority": priority,
                "is_active": is_active,
            },
        )
        row = await self.get_provider(user_id, provider_id)
        assert row is not None  # RLS insert returned the id we just wrote
        return row

    async def delete_provider(self, user_id: uuid.UUID, provider_id: uuid.UUID) -> bool:
        """Delete a provider and its ``rate_limit_state`` rows atomically."""
        provider = await self.get_provider(user_id, provider_id)
        if provider is None:
            return False
        await self.db.execute(
            "DELETE FROM rate_limit_state WHERE provider_name = %s AND user_id = %s",
            (provider["name"], str(user_id)),
        )
        cursor = await self.db.execute(
            "DELETE FROM llm_providers WHERE id = %s AND user_id = %s", (str(provider_id), str(user_id))
        )
        return cursor.rowcount == 1

    # --------------------------------------------------------------- usage
    async def insert_usage(
        self,
        user_id: uuid.UUID,
        *,
        provider_id: uuid.UUID,
        job_id: uuid.UUID | None,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: int,
        success: bool,
        error_type: str | None = None,
    ) -> None:
        await self.insert(
            "provider_usage",
            {
                "user_id": user_id,
                "provider_id": provider_id,
                "job_id": job_id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "latency_ms": latency_ms,
                "success": success,
                "error_type": error_type,
            },
            returning=None,
        )

    # ------------------------------------------------------------ breakers
    async def get_breaker(self, user_id: uuid.UUID, provider_name: str) -> dict[str, Any] | None:
        row = await (
            await self.db.execute(
                "SELECT state, failure_count, last_failure_at, cooldown_expires_at "
                "FROM rate_limit_state WHERE provider_name = %s AND user_id = %s",
                (provider_name, str(user_id)),
            )
        ).fetchone()
        if row is None:
            return None
        return {
            "provider_name": provider_name,
            "state": row[0],
            "failure_count": row[1],
            "last_failure_at": row[2],
            "cooldown_expires_at": row[3],
        }

    async def ensure_breaker(self, user_id: uuid.UUID, provider_name: str) -> None:
        """Create a CLOSED breaker row on first failure (idempotent upsert)."""
        await self.db.execute(
            "INSERT INTO rate_limit_state (user_id, provider_name) VALUES (%s, %s) "
            "ON CONFLICT (provider_name, user_id) DO NOTHING",
            (str(user_id), provider_name),
        )

    async def claim_trial(self, user_id: uuid.UUID, provider_name: str, *, now: datetime) -> bool:
        """OPEN -> HALF_OPEN + claim the single trial, or claim a fresh HALF_OPEN trial.

        The same guarded UPDATE lazy-transitions the state and locks the trial by
        pushing ``cooldown_expires_at`` into the future; a concurrent peer sees the
        new ``cooldown_expires_at`` and gets rowcount 0 -> it must NOT call the
        provider (no double-trial, D16).
        """
        cursor = await self.db.execute(
            "UPDATE rate_limit_state "
            "SET state = 'HALF_OPEN', cooldown_expires_at = %s, updated_at = NOW() "
            "WHERE provider_name = %s AND user_id = %s "
            "AND state IN ('OPEN', 'HALF_OPEN') "
            "AND (cooldown_expires_at IS NULL OR cooldown_expires_at <= %s)",
            (
                now + timedelta(seconds=TRIAL_WINDOW_SECONDS),
                provider_name,
                str(user_id),
                now,
            ),
        )
        return cursor.rowcount == 1

    async def increment_failure(
        self,
        user_id: uuid.UUID,
        provider_name: str,
        *,
        current_failure_count: int,
        last_failure_at: datetime,
    ) -> bool:
        """Count one consecutive failure; the guard makes concurrent increments single-shot."""
        cursor = await self.db.execute(
            "UPDATE rate_limit_state "
            "SET failure_count = failure_count + 1, last_failure_at = %s, updated_at = NOW() "
            "WHERE provider_name = %s AND user_id = %s "
            "AND state IN ('CLOSED', 'HALF_OPEN') AND failure_count = %s",
            (last_failure_at, provider_name, str(user_id), current_failure_count),
        )
        return cursor.rowcount == 1

    async def trip_circuit(
        self,
        user_id: uuid.UUID,
        provider_name: str,
        *,
        failure_count_delta: int,
        cooldown_expires_at: datetime,
        last_failure_at: datetime,
        observed_state: str,
    ) -> bool:
        """Open the circuit (guarded by the observed state). ``delta=0`` for 429s."""
        cursor = await self.db.execute(
            "UPDATE rate_limit_state "
            "SET state = 'OPEN', failure_count = failure_count + %s, "
            "cooldown_expires_at = %s, last_failure_at = %s, updated_at = NOW() "
            "WHERE provider_name = %s AND user_id = %s AND state = %s",
            (
                failure_count_delta,
                cooldown_expires_at,
                last_failure_at,
                provider_name,
                str(user_id),
                observed_state,
            ),
        )
        return cursor.rowcount == 1

    async def reset_circuit(self, user_id: uuid.UUID, provider_name: str, *, observed_state: str) -> bool:
        """Reset to CLOSED (success in HALF_OPEN/CLOSED); guarded by the observed state."""
        cursor = await self.db.execute(
            "UPDATE rate_limit_state "
            "SET state = 'CLOSED', failure_count = 0, cooldown_expires_at = NULL, "
            "last_failure_at = NULL, updated_at = NOW() "
            "WHERE provider_name = %s AND user_id = %s AND state = %s",
            (provider_name, str(user_id), observed_state),
        )
        return cursor.rowcount == 1
