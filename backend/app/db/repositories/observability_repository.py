"""observability repository — owns audit_logs, error_logs.

Insert lanes for the shared audit/error tables. ``user_id`` never comes from a caller
parameter: it is read from the scoped ``DbContext``, so a row can only ever be written
for the identity the transaction is scoped to (RLS WITH CHECK re-verifies this).
"""

from __future__ import annotations

import ipaddress
from typing import Any

from backend.app.db.repositories.base import BaseRepository


class ObservabilityRepository(BaseRepository):
    """observability owns audit + error log tables."""

    owns = frozenset({"audit_logs", "error_logs"})

    async def insert_audit(
        self,
        *,
        action: str,
        resource_type: str,
        resource_id: Any = None,
        details: dict[str, Any] | None = None,
        ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None,
    ) -> Any:
        if self.db.user_id is None:
            raise ValueError("audit write requires an authenticated DbContext")
        return await self.insert(
            "audit_logs",
            {
                "user_id": self.db.user_id,
                "action": action,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "details": details or {},
                "ip_address": ip_address,
            },
        )

    async def insert_error(
        self,
        *,
        component: str,
        error_type: str,
        severity: str,
        message: str,
        context: dict[str, Any] | None = None,
        provider: str | None = None,
        job_id: str | None = None,
        next_action: str | None = None,
    ) -> Any:
        """Structured row in ``error_logs`` (owned here); scoped to the active user."""
        if self.db.user_id is None:
            raise ValueError("error log write requires an authenticated DbContext")
        return await self.insert(
            "error_logs",
            {
                "user_id": self.db.user_id,
                "component": component,
                "error_type": error_type,
                "severity": severity,
                "message": message,
                "context": context or {},
                "provider": provider,
                "job_id": job_id,
                "retry_count": 0,
                "next_action": next_action,
            },
        )
