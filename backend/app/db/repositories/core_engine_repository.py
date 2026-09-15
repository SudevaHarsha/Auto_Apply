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

_JOB_SUMMARY_COLUMNS = [
    "id",
    "title",
    "company",
    "url",
    "platform",
    "status",
    "score",
    "freshness_state",
    "created_at",
]
_JOB_DETAIL_COLUMNS = [
    "id",
    "title",
    "company",
    "url",
    "platform",
    "source",
    "status",
    "score",
    "raw_message",
    "freshness_state",
    "content_hash",
    "current_snapshot_id",
    "last_fetched_at",
    "created_at",
    "updated_at",
]
_VALID_JOB_STATUSES = frozenset(
    {"discovered", "scored", "approved", "applying", "applied", "rejected", "skipped", "failed"}
)
_VALID_PLATFORMS = frozenset({"greenhouse", "lever", "linkedin", "indeed", "workday", "generic"})


class CoreEngineRepository(BaseRepository):
    """core_engine owns profile/job/application/pipeline data plus the shared job_snapshots cache."""

    owns = frozenset({"profiles", "jobs", "applications", "pipeline_runs", "job_snapshots"})

    async def upsert_snapshot(
        self, content_hash: str, payload: dict[str, Any], *, raw_text: str | None = None
    ) -> uuid.UUID:
        """Shared, concurrency-safe snapshot write (I1/I4).

        ``job_snapshots`` is RLS-exempt (no ``user_id``). Unique ``content_hash`` means N
        concurrent identical fetches insert at most one row; whoever lands the INSERT wins,
        everyone else matches the SELECT fallback. ``raw_text`` (D28) is the cleaned text
        the cascade built — never the raw fetched HTML.
        """
        row = await (
            await self.db.execute(
                """INSERT INTO job_snapshots (content_hash, payload, raw_text)
                   VALUES (%s, %s, %s)
                   ON CONFLICT (content_hash) DO NOTHING
                   RETURNING id""",
                (content_hash, Jsonb(payload), raw_text),
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

    async def find_snapshot_by_source_url(self, url: str) -> dict[str, Any] | None:
        """URL-keyed fast path (I4) — "no new fetch for user 2".

        No dedicated index (migration-count invariants must stay at 40): the dedup'd
        ``job_snapshots`` table is tiny, so the jsonb path scan is fine.
        """
        cur = await self.db.execute(
            """SELECT id, content_hash, payload, raw_text
               FROM job_snapshots
               WHERE payload->'_meta'->>'source_url' = %s
               ORDER BY captured_at DESC LIMIT 1""",
            (url,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "content_hash": row[1],
            "payload": row[2],
            "raw_text": row[3],
        }

    # -------------------------------------------------------------- jobs (S6)
    async def find_job_by_url(self, user_id: uuid.UUID, url: str) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT id, title, company, url, platform, source, status, score,"
            " raw_message, freshness_state, content_hash, current_snapshot_id,"
            " last_fetched_at, created_at FROM jobs WHERE user_id = %s AND url = %s",
            (str(user_id), url),
        )
        return self._job_row(await cur.fetchone())

    async def apply_snapshot(self, *, job_id: uuid.UUID, snapshot_id: uuid.UUID, content_hash: str) -> None:
        """Bind the latest snapshot to the job + reset freshness (I2/§6/§10)."""
        await self.db.execute(
            """UPDATE jobs
               SET current_snapshot_id = %s, content_hash = %s,
                   freshness_state = 'fresh', last_fetched_at = NOW(), updated_at = NOW()
               WHERE id = %s""",
            (str(snapshot_id), content_hash, str(job_id)),
        )

    async def mark_freshness(self, job_id: uuid.UUID, state: str) -> bool:
        cur = await self.db.execute("UPDATE jobs SET freshness_state = %s WHERE id = %s", (state, str(job_id)))
        return cur.rowcount == 1

    async def touch_last_fetched(self, job_id: uuid.UUID) -> None:
        """Same-content refresh: bump ``last_fetched_at`` only (I2, hash-match path)."""
        await self.db.execute("UPDATE jobs SET last_fetched_at = NOW() WHERE id = %s", (str(job_id),))

    async def list_jobs(
        self,
        user_id: uuid.UUID,
        *,
        status: str | None = None,
        platform: str | None = None,
        limit: int = 20,
        cursor: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Keyset cursor pagination (ORDER BY created_at DESC, id DESC); cursor = ``<iso>|<id>``."""
        limit = max(1, min(int(limit), 100))
        clauses = ["user_id = %s"]
        params: list[Any] = [str(user_id)]
        if status:
            clauses.append("status = %s")
            params.append(status)
        if platform:
            clauses.append("platform = %s")
            params.append(platform)
        if cursor:
            created_at_raw, separator, job_id_raw = cursor.partition("|")
            if separator:
                clauses.append("(created_at, id) < (%s, %s)")
                params.extend([created_at_raw, job_id_raw])
        clauses.append("LIMIT %s")
        params.append(limit + 1)
        cur = await self.db.execute(
            "SELECT id, title, company, url, platform, status, score, freshness_state, created_at"
            f" FROM jobs WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, id DESC",
            params,
        )
        rows = [dict(zip(_JOB_SUMMARY_COLUMNS, r, strict=False)) for r in await cur.fetchall()]
        has_more = len(rows) > limit
        rows = rows[:limit]
        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            next_cursor = f"{last['created_at'].isoformat()}|{last['id']}"
        return rows, next_cursor

    async def get_job_detail(self, user_id: uuid.UUID, job_id: uuid.UUID) -> dict[str, Any] | None:
        cur = await self.db.execute(
            """SELECT j.id, j.title, j.company, j.url, j.platform, j.source, j.status,
                      j.score, j.raw_message, j.freshness_state, j.content_hash,
                      j.current_snapshot_id, j.last_fetched_at, j.created_at, j.updated_at,
                      s.raw_text, s.payload
               FROM jobs j
               LEFT JOIN job_snapshots s ON s.id = j.current_snapshot_id
               WHERE j.user_id = %s AND j.id = %s""",
            (str(user_id), str(job_id)),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "title": row[1],
            "company": row[2],
            "url": row[3],
            "platform": row[4],
            "source": row[5],
            "status": row[6],
            "score": row[7],
            "raw_message": row[8],
            "freshness_state": row[9],
            "content_hash": row[10],
            "current_snapshot_id": row[11],
            "last_fetched_at": row[12],
            "created_at": row[13],
            "updated_at": row[14],
            "raw_text": row[15],
            "payload": row[16],
        }

    async def update_job_status(self, user_id: uuid.UUID, job_id: uuid.UUID, status: str) -> bool:
        if status not in _VALID_JOB_STATUSES:
            raise ValueError(f"invalid job status {status!r}")
        cur = await self.db.execute(
            "UPDATE jobs SET status = %s, updated_at = NOW() WHERE user_id = %s AND id = %s",
            (status, str(user_id), str(job_id)),
        )
        return cur.rowcount == 1

    async def delete_job(self, user_id: uuid.UUID, job_id: uuid.UUID) -> bool:
        cur = await self.db.execute("DELETE FROM jobs WHERE user_id = %s AND id = %s", (str(user_id), str(job_id)))
        return cur.rowcount == 1

    @staticmethod
    def _job_row(row: tuple[Any, ...] | None) -> dict[str, Any] | None:
        if row is None:
            return None
        return dict(
            zip(
                [
                    "id",
                    "title",
                    "company",
                    "url",
                    "platform",
                    "source",
                    "status",
                    "score",
                    "raw_message",
                    "freshness_state",
                    "content_hash",
                    "current_snapshot_id",
                    "last_fetched_at",
                    "created_at",
                ],
                row,
                strict=False,
            )
        )

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
