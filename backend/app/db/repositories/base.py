"""BaseRepository — thin, table-qualified, RLS-scoped CRUD shared by S2 repositories.

Each repository declares the set of tables it *owns* (see
``plans/autoapply-implementation.md`` §2 Ownership). All SQL runs through the owning
``DbContext`` so every statement is scoped to the current user by RLS. A repository may
only touch tables in its ``owns`` set (enforced at runtime and by the ownership guard
test in T2).
"""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from backend.app.db.context import DbContext


class BaseRepository:
    """Fixed set of tables this component owns; all access RLS-scoped via DbContext."""

    owns: frozenset[str] = frozenset()

    def __init__(self, db: DbContext) -> None:
        self.db = db

    def _check(self, table: str) -> None:
        if table not in self.owns:
            raise ValueError(f"{type(self).__name__} does not own table {table!r}")

    @staticmethod
    def _dump(value: Any) -> Any:
        """Wrap dict/list as jsonb for psycopg3 so JSON columns serialize correctly."""
        if isinstance(value, (dict, list)):
            return Jsonb(value)
        return value

    async def insert(
        self,
        table: str,
        columns: dict[str, Any],
        returning: str | None = "id",
    ) -> Any:
        """Insert one row; returns the value of ``returning`` (or None if not requested).

        The RLS policy (WITH CHECK defaults to USING) requires the inserted row's scoping
        column to equal the active ``app.user_id``; callers pass it in ``columns``.
        """
        self._check(table)
        if not columns:
            raise ValueError("insert requires at least one column")
        names = ", ".join(columns.keys())
        placeholders = ", ".join("%s" for _ in columns)
        sql = f"INSERT INTO {table} ({names}) VALUES ({placeholders})"
        params = [self._dump(v) for v in columns.values()]
        if returning:
            sql += f" RETURNING {returning}"
            row = await (await self.db.execute(sql, params)).fetchone()
            return row[0] if row else None
        await self.db.execute(sql, params)
        return None

    async def count(self, table: str) -> int:
        """Count rows visible to the current RLS user in ``table``."""
        self._check(table)
        value = await self.db.fetch_scalar(f"SELECT count(*) FROM {table}")
        return int(value or 0)

    async def exists(self, table: str, id_col: str, value: uuid.UUID | str) -> bool:
        self._check(table)
        n = await self.db.fetch_scalar(
            f"SELECT count(*) FROM {table} WHERE {id_col} = %s", (str(value),)
        )
        return bool(n)
