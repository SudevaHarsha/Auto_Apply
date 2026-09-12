"""core_engine repository — owns profiles, jobs, applications, pipeline_runs, job_snapshots."""

from __future__ import annotations

import uuid
from typing import Any

from psycopg.types.json import Jsonb

from backend.app.db.repositories.base import BaseRepository


def _row(record: tuple[Any, ...] | None, columns: list[str]) -> dict[str, Any] | None:
    if record is None:
        return None
    return {name: value for name, value in zip(columns, record, strict=False)}


_PROFILE_COLUMNS = ["id", "user_id", "original_pdf_url", "json_resume", "pdf_sha256", "last_scored_at", "created_at"]
_PROFILE_SUMMARY_COLUMNS = ["id", "original_pdf_url", "pdf_sha256", "last_scored_at", "created_at"]


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

    # -------------------------------------------------------------- profiles (S5)
    async def find_by_sha256(self, user_id: uuid.UUID, sha256: str) -> dict[str, Any] | None:
        """O(1) idempotency pre-check (D23): existing row for (user, pdf_sha256)."""
        cur = await self.db.execute(
            "SELECT id, original_pdf_url, last_scored_at, created_at, json_resume"
            " FROM profiles WHERE user_id = %s AND pdf_sha256 = %s ORDER BY created_at DESC LIMIT 1",
            (str(user_id), sha256),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return dict(zip(["id", "original_pdf_url", "last_scored_at", "created_at", "json_resume"], row, strict=False))

    async def list_profiles(self, user_id: uuid.UUID) -> list[dict[str, Any]]:
        """All profiles for the user, most recent first; summary columns only (no json_resume, §8)."""
        cur = await self.db.execute(
            "SELECT id, original_pdf_url, last_scored_at, created_at"
            " FROM profiles WHERE user_id = %s ORDER BY created_at DESC",
            (str(user_id),),
        )
        rows = await cur.fetchall()
        return [dict(zip(["id", "original_pdf_url", "last_scored_at", "created_at"], r, strict=False)) for r in rows]

    async def get_profile(self, user_id: uuid.UUID, profile_id: uuid.UUID) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT id, original_pdf_url, json_resume, last_scored_at, created_at"
            " FROM profiles WHERE user_id = %s AND id = %s",
            (str(user_id), str(profile_id)),
        )
        return _row(await cur.fetchone(), ["id", "original_pdf_url", "json_resume", "last_scored_at", "created_at"])

    async def get_current_profile(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT id, original_pdf_url, json_resume, last_scored_at, created_at"
            " FROM profiles WHERE user_id = %s ORDER BY created_at DESC LIMIT 1",
            (str(user_id),),
        )
        return _row(await cur.fetchone(), ["id", "original_pdf_url", "json_resume", "last_scored_at", "created_at"])

    async def insert_profile(
        self,
        user_id: uuid.UUID,
        *,
        profile_id: uuid.UUID,
        original_pdf_url: str,
        json_resume: dict[str, Any],
        pdf_sha256: str,
    ) -> uuid.UUID:
        row = await (
            await self.db.execute(
                """INSERT INTO profiles (id, user_id, original_pdf_url, json_resume, pdf_sha256)
                   VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                (str(profile_id), str(user_id), original_pdf_url, Jsonb(json_resume), pdf_sha256),
            )
        ).fetchone()
        if row is None:  # pragma: no cover - defensive
            raise RuntimeError("profiles INSERT returned no id")
        return row[0]

    async def update_profile(self, user_id: uuid.UUID, profile_id: uuid.UUID, json_resume: dict[str, Any]) -> bool:
        cur = await self.db.execute(
            "UPDATE profiles SET json_resume = %s WHERE user_id = %s AND id = %s",
            (Jsonb(json_resume), str(user_id), str(profile_id)),
        )
        return cur.rowcount == 1
