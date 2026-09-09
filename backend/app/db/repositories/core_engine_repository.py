"""core_engine repository — owns profiles, jobs, applications, pipeline_runs, job_snapshots."""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from backend.app.db.repositories.base import BaseRepository


class CoreEngineRepository(BaseRepository):
    """core_engine owns profile/job/application/pipeline data plus the shared job_snapshots cache."""

    owns = frozenset({"profiles", "jobs", "applications", "pipeline_runs", "job_snapshots"})

    async def upsert_snapshot(self, content_hash: str, payload: dict[str, Any]) -> uuid.UUID:
        """Shared, concurrency-safe snapshot write (I1/I4).

        ``job_snapshots`` is RLS-exempt (no ``user_id``). Unique ``content_hash`` means N
        concurrent identical fetches insert at most one row; whoever lands the INSERT wins,
        everyone else matches the SELECT fallback.
        """
        row = await (
            await self.db.execute(
                """INSERT INTO job_snapshots (content_hash, payload)
                   VALUES (%s, %s)
                   ON CONFLICT (content_hash) DO NOTHING
                   RETURNING id""",
                (content_hash, Jsonb(payload)),
            )
        ).fetchone()
        if row is not None:
            return row[0]
        got = await (
            await self.db.execute("SELECT id FROM job_snapshots WHERE content_hash = %s", (content_hash,))
        ).fetchone()
        if got is None:  # pragma: no cover - defensive
            raise RuntimeError(f"snapshot {content_hash!r} vanished between insert and select")
        return got[0]
