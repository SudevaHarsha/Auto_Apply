"""LLM provider service — maps 1:1 to canonical §12 endpoints (D13).

No HTTP surface on llm_router; these service functions are what ``backend_api``
(S14) will wire to ``GET/POST /api/llm/providers``, ``DELETE .../{id}`` and
``POST /api/llm/test``. Every operation runs inside ``DbContext.transaction()``
(RLS-scoped), encrypts keys at rest (D18) and audits through the observability lane.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import psycopg

from backend.app.db.context import DbContext
from backend.app.db.repositories.llm_router_repository import LlmRouterRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository
from backend.app.llm.adapters.base import ProviderAdapter
from backend.app.llm.crypto import DecryptionError, decrypt_provider_key, encrypt_provider_key
from backend.app.llm.errors import (
    ProviderDuplicateError,
    ProviderNotFoundError,
    ProviderTestFailedError,
    ValidationError,
)
from backend.app.llm.registry import registered_names, spec_for
from backend.app.llm.router import DEFAULT_TIMEOUT_SECONDS


@dataclass
class ProviderOut:
    id: str
    name: str
    base_url: str
    model: str
    is_active: bool
    priority: int
    created_at: datetime


def _to_out(row: dict[str, Any]) -> ProviderOut:
    return ProviderOut(
        id=str(row["id"]),
        name=row["name"],
        base_url=row["base_url"],
        model=row["model"],
        is_active=row["is_active"],
        priority=row["priority"],
        created_at=row["created_at"],
    )


class LlmProviderService:
    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self.conn = conn

    async def list_providers(self, *, user_id: uuid.UUID) -> list[ProviderOut]:
        async with DbContext(self.conn, user_id).transaction() as db:
            rows = await LlmRouterRepository(db).list_providers(user_id)
        return [_to_out(row) for row in rows]

    async def add_provider(
        self,
        *,
        user_id: uuid.UUID,
        name: str,
        base_url: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
        priority: int = 0,
    ) -> ProviderOut:
        name = name.strip().lower()
        spec = spec_for(name)
        if spec is None:
            raise ValidationError(
                f"unknown provider {name!r}",
                details={"name": name, "known_providers": list(registered_names())},
            )
        base_url = (base_url or spec.default_base_url).strip()
        model = (model or spec.default_model).strip()
        if not base_url or not model:
            raise ValidationError("base_url and model must be non-empty", details={"name": name})
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise ValidationError("priority must be an integer", details={"priority": priority})

        api_key_encrypted = encrypt_provider_key(api_key) if api_key else None

        async with DbContext(self.conn, user_id).transaction() as db:
            repo = LlmRouterRepository(db)
            if await repo.count_providers_by_name(user_id, name):
                raise ProviderDuplicateError(
                    f"provider {name!r} already exists",
                    details={"name": name},
                )
            row = await repo.create_provider(
                user_id,
                name=name,
                base_url=base_url,
                model=model,
                api_key_encrypted=api_key_encrypted,
                priority=priority,
                is_active=True,
            )
            await ObservabilityRepository(db).insert_audit(
                action="llm_provider_added",
                resource_type="provider",
                resource_id=row["id"],
                details={"provider": name, "model": model, "priority": priority, "has_api_key": bool(api_key)},
            )
        return _to_out(row)

    async def delete_provider(self, *, user_id: uuid.UUID, provider_id: uuid.UUID) -> None:
        async with DbContext(self.conn, user_id).transaction() as db:
            repo = LlmRouterRepository(db)
            row = await repo.get_provider(user_id, provider_id)
            if row is None:
                raise ProviderNotFoundError(
                    f"provider {provider_id} not found",
                    details={"provider_id": str(provider_id)},
                )
            await repo.delete_provider(user_id, provider_id)
            await ObservabilityRepository(db).insert_audit(
                action="llm_provider_removed",
                resource_type="provider",
                resource_id=row["id"],
                details={"provider": row["name"]},
            )

    async def test_provider(
        self,
        *,
        user_id: uuid.UUID,
        provider_id: uuid.UUID,
        prompt: str,
        adapter_factory: Callable[[str], ProviderAdapter] | None = None,
    ) -> dict[str, Any]:
        async with DbContext(self.conn, user_id).transaction() as db:
            repo = LlmRouterRepository(db)
            row = await repo.get_provider(user_id, provider_id)
            if row is None:
                raise ProviderNotFoundError(
                    f"provider {provider_id} not found",
                    details={"provider_id": str(provider_id)},
                )
            spec = spec_for(row["name"])
            if spec is None:
                raise ValidationError(f"unregistered provider {row['name']!r}", details={"name": row["name"]})
            api_key: str | None = None
            if row.get("api_key_encrypted"):
                try:
                    api_key = decrypt_provider_key(row["api_key_encrypted"])
                except DecryptionError as exc:
                    raise ProviderTestFailedError(
                        "provider probe failed: cannot decrypt stored key",
                        details={"provider": row["name"], "status_code": None, "error_type": "invalid_key"},
                    ) from exc
            adapter = adapter_factory(row["name"]) if adapter_factory is not None else spec.adapter()
            response = await asyncio.to_thread(
                adapter.chat,
                prompt=prompt,
                system_message=None,
                model=row["model"],
                base_url=row["base_url"],
                api_key=api_key,
                json_mode=False,
                output_schema=None,
                timeout=DEFAULT_TIMEOUT_SECONDS,
            )
        if response.status == "ok":
            return {
                "success": True,
                "response": response.content or "",
                "latency_ms": response.latency_ms,
                "model": response.model or row["model"],
            }
        raise ProviderTestFailedError(
            "provider probe failed",
            details={
                "provider": row["name"],
                "status_code": response.status_code,
                "error_type": response.error_type or ("timeout" if response.status == "timeout" else "http_error"),
            },
        )
