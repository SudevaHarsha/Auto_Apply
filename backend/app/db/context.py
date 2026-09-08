"""Per-request RLS-scoped transaction wrapper (S2).

Working name: the docs specify this pattern via ``get_db()`` / ``SET LOCAL app.user_id``
(see ``docs/architecture/security_boundaries.md`` and ``docs/api_contracts/schema.md``) but
never name it, so we call it :class:`DbContext`.

Semantics:
- Every query runs inside a transaction that first issues
  ``set_config('app.user_id', %s, true)`` (the ``SET LOCAL`` equivalent). It is scoped to
  the transaction and auto-clears on commit/rollback, so no identity leaks between requests
  or across pooled connections.
- ``user_id=None`` is allowed for system/anonymous contexts but must be explicit. The
  anonymous identity maps to the zero-UUID sentinel ``NO_USER``: `user_id = '0000...0'::uuid`
  matches no real row (``uuid_generate_v4()`` never produces it), so every policy table is
  default-denied. A true ``NULL`` GUC is NOT achievable via ``set_config(..., NULL, true)``
  (Postgres stores ``''`` and ``''::uuid`` raises) and a *never-set* GUC makes
  ``current_setting('app.user_id')`` raise ``UndefinedObject`` — both fail-closed, but the
  sentinel is the only deterministic 0-row path (D5, see ``tests/integration/README.md``).
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from typing import Any

import psycopg

NO_USER = "00000000-0000-0000-0000-000000000000"


class DbContext:
    """Owns an async connection and scopes every transaction to ``user_id`` via RLS."""

    def __init__(self, conn: psycopg.AsyncConnection, user_id: uuid.UUID | None) -> None:
        self.conn = conn
        self.user_id = user_id

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[DbContext]:
        """Run a block as one RLS-scoped transaction (commit on success, rollback on error)."""
        async with self.conn.transaction():
            await self._set_user_context()
            yield self

    async def _set_user_context(self) -> None:
        # set_config(..., true) == SET LOCAL: scoped to the current transaction only.
        # user_id=None -> zero-UUID sentinel -> default-denied (matches no row).
        value = str(self.user_id) if self.user_id is not None else NO_USER
        await self.conn.execute("SELECT set_config('app.user_id', %s, true)", (value,))

    async def execute(
        self, query: str, params: Sequence[Any] | None = None
    ) -> psycopg.AsyncCursor[tuple[Any, ...]]:
        return await self.conn.execute(query, params)

    async def fetch_scalar(
        self, query: str, params: Sequence[Any] | None = None
    ) -> Any:
        row = await (await self.conn.execute(query, params)).fetchone()
        return row[0] if row else None
