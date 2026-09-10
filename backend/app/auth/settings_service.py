"""SettingsService — GET/PUT /api/auth/settings (api_contracts §17).

Read: defaults ∪ stored (stored rows win). Write: key whitelist + per-key value
validation, upsert, then re-read as the merged payload. All runs inside a DbContext
scoped to ``user_id``; cross-user rows are invisible/denied by RLS.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from backend.app.auth.errors import (
    SettingsKeyInvalidError,
    SettingsValueInvalidError,
)
from backend.app.db.context import DbContext
from backend.app.db.repositories.auth_repository import AuthRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository
from backend.app.llm.registry import registered_names

# §17 authoritative schema: key -> (validator, default)
# D19: llm_chain is validated against the provider registry, not a fixed 4-name list.
_LLM_PROVIDERS = tuple(registered_names())


def _validate_int_ranged(min_value: int, max_value: int):
    def _check(value: Any) -> int:
        if isinstance(value, bool) or not isinstance(value, int):
            raise SettingsValueInvalidError(
                "auto_approve_threshold must be an integer", details={"auto_approve_threshold": value}
            )
        if not (min_value <= value <= max_value):
            raise SettingsValueInvalidError(
                f"auto_approve_threshold must be between {min_value} and {max_value}",
                details={"auto_approve_threshold": value},
            )
        return value

    return _check


def _validate_choice(*choices: str):
    def _check(value: Any) -> str:
        if not isinstance(value, str) or value not in choices:
            raise SettingsValueInvalidError(f"value must be one of {choices}", details={"value": value})
        return value

    return _check


def _validate_bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise SettingsValueInvalidError("value must be a boolean", details={"value": value})
    return value


def _validate_llm_chain(value: Any) -> list[str]:
    if not isinstance(value, list) or not value or not all(isinstance(v, str) and v in _LLM_PROVIDERS for v in value):
        raise SettingsValueInvalidError(
            "llm_chain must be a non-empty list of known providers",
            details={"value": value},
        )
    return list(value)


SETTINGS_SPEC: dict[str, tuple[Any, Any]] = {
    "chat_mode": (_validate_choice("bot", "agent"), "bot"),
    "theme": (_validate_choice("dark", "light"), "dark"),
    "auto_approve_threshold": (_validate_int_ranged(0, 100), 80),
    "notifications_enabled": (_validate_bool, True),
    "llm_chain": (_validate_llm_chain, ["gemini", "ollama", "groq", "openrouter"]),
}

SETTINGS_SPEC_NAMES_WITH_DEFAULTS: dict[str, Any] = {key: spec[1] for key, spec in SETTINGS_SPEC.items()}


class SettingsService:
    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self.conn = conn

    async def get(self, *, user_id: uuid.UUID) -> dict[str, Any]:
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            rows = await AuthRepository(db).get_settings(user_id)
        merged: dict[str, Any] = dict(SETTINGS_SPEC_NAMES_WITH_DEFAULTS)
        for key, value, _updated in rows:
            if key in merged:  # stored always wins for known keys
                merged[key] = value
        return merged

    async def update(self, *, user_id: uuid.UUID, updates: dict[str, Any]) -> dict[str, Any]:
        unknown = [key for key in updates if key not in SETTINGS_SPEC]
        if unknown:
            raise SettingsKeyInvalidError("unknown settings key", details={"keys": unknown})
        validated: dict[str, Any] = {}
        for key, validator in ((k, SETTINGS_SPEC[k][0]) for k in updates):
            try:
                validated[key] = validator(updates[key])
            except SettingsValueInvalidError as exc:
                exc.details["key"] = key
                raise exc
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            repo = AuthRepository(db)
            for key, value in validated.items():
                await repo.upsert_setting(user_id, key, value)
            await ObservabilityRepository(db).insert_audit(
                action="settings_updated",
                resource_type="settings",
                resource_id=None,
                details={"keys": sorted(validated)},
            )
            rows = await repo.get_settings(user_id)
        merged: dict[str, Any] = dict(SETTINGS_SPEC_NAMES_WITH_DEFAULTS)
        for key, value, _updated in rows:
            merged[key] = value
        return merged
