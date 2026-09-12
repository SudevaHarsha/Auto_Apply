"""ProfilesService — core-engine profile CRUD mapping 1:1 to §8 (S5).

Upload/list/current/update are service functions only (no HTTP — that is
``backend_api``, S14), mirroring AuthService's stateless-orchestrator pattern:
constructed with a connection, each operation opens its own
``DbContext.transaction()`` scoped to the calling user, audits are written via
``ObservabilityRepository`` (I5).

Upload semantics (D23/D24): validate ``.pdf`` + ``%PDF-`` magic + ≤10MB
(§8); sha256 pre-check first (partial unique index ``idx_profiles_user_sha256``
makes duplicates impossible regardless of app state); a match returns the
*existing* profile row with zero LLM calls and zero extra audit; else persist
the PDF to ``{storage_root}/profiles/{user_id}/{profile_id}/original.pdf``,
extract, and only then INSERT + audit ``profile_uploaded`` (D24: PUT also logs
``profile_uploaded`` — the canonical literal).
"""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import psycopg

from backend.app.core_engine import storage
from backend.app.core_engine.errors import ProfileNotFoundError, ValidationError
from backend.app.core_engine.extraction import extract_profile, sha256_hex
from backend.app.db.context import DbContext
from backend.app.db.repositories.core_engine_repository import CoreEngineRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository
from backend.app.llm.adapters.base import ProviderAdapter

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # §8: max 10MB


@dataclass(frozen=True)
class ProfileOut:
    id: uuid.UUID
    original_pdf_url: str
    json_resume: dict[str, Any]
    last_scored_at: dt.datetime | None
    created_at: dt.datetime


@dataclass(frozen=True)
class ProfileSummary:
    id: uuid.UUID
    original_pdf_url: str
    last_scored_at: dt.datetime | None
    created_at: dt.datetime


def _validate_pdf_upload(filename: str | None, payload: bytes) -> None:
    """§8 upload guard: extension + magic bytes + size cap → ValidationError."""
    if filename is not None and not filename.lower().endswith(".pdf"):
        raise ValidationError("file must have a .pdf extension", details={"filename": filename})
    if not payload.startswith(b"%PDF-"):
        raise ValidationError("file is not a PDF")
    if len(payload) > MAX_UPLOAD_BYTES:
        raise ValidationError(
            "file exceeds the 10MB upload limit",
            details={"max_bytes": MAX_UPLOAD_BYTES, "actual_bytes": len(payload)},
        )


def _to_profile_out(row: dict[str, Any]) -> ProfileOut:
    return ProfileOut(
        id=row["id"],
        original_pdf_url=row["original_pdf_url"],
        json_resume=row["json_resume"],
        last_scored_at=row["last_scored_at"],
        created_at=row["created_at"],
    )


class ProfilesService:
    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self.conn = conn

    # ------------------------------------------------------------- upload (POST §8)
    async def upload_profile(
        self,
        *,
        user_id: uuid.UUID,
        pdf_path: str,
        sha256: str | None = None,
        filename: str | None = None,
        adapter_factory: Callable[[str], ProviderAdapter] | None = None,
    ) -> ProfileOut:
        """POST /api/profiles/upload (service layer). Idempotent per (user, sha256).

        ``adapter_factory`` is the D26 test-only seam: the S4 ``mock_provider``
        is threaded through to ``extract_profile`` → ``route_llm_request`` so the
        offline T5 suite needs no real provider keys.
        """
        payload = storage.read_pdf(pdf_path)
        _validate_pdf_upload(filename, payload)
        digest = sha256 or sha256_hex(payload)

        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            repo = CoreEngineRepository(db)
            existing = await repo.find_by_sha256(user_id, digest)
            if existing is not None:
                # D23: same bytes → same profile row; no LLM, no file, no audit.
                return _to_profile_out(existing)
            profile_id = uuid.uuid4()
            url = storage.save_pdf(user_id, profile_id, payload)

        # Extraction is intentionally OUTSIDE the insert transaction: the router's
        # provider_usage/audit writes commit independently, so LLM call telemetry
        # survives an extraction failure (idempotent retries still re-verify sha).
        try:
            resume = await extract_profile(
                self.conn,
                user_id=user_id,
                pdf_path=str(storage.original_pdf_path(user_id, profile_id)),
                adapter_factory=adapter_factory,
            )
        except Exception:
            storage.delete_pdf(user_id, profile_id)
            raise

        async with db.transaction():
            repo = CoreEngineRepository(db)
            await repo.insert_profile(
                user_id,
                profile_id=profile_id,
                original_pdf_url=url,
                json_resume=resume.model_dump(mode="json"),
                pdf_sha256=digest,
            )
            await ObservabilityRepository(db).insert_audit(
                action="profile_uploaded",
                resource_type="profile",
                resource_id=str(profile_id),
                details={"sha256": digest},
            )
            row = await repo.get_profile(user_id, profile_id)
        if row is None:  # pragma: no cover - defensive
            raise ProfileNotFoundError("profile was not created", details={"profile_id": str(profile_id)})
        return _to_profile_out(row)

    # ------------------------------------------------------------------ list (GET §8)
    async def list_profiles(self, *, user_id: uuid.UUID) -> list[ProfileSummary]:
        """GET /api/profiles — summaries only (no json_resume in list, §8)."""
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            rows = await CoreEngineRepository(db).list_profiles(user_id)
        return [
            ProfileSummary(
                id=r["id"],
                original_pdf_url=r["original_pdf_url"],
                last_scored_at=r["last_scored_at"],
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # -------------------------------------------------------- current (GET §8)
    async def get_current_profile(self, *, user_id: uuid.UUID) -> ProfileOut:
        """GET /api/profiles/current — most recent profile, full json_resume."""
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            row = await CoreEngineRepository(db).get_current_profile(user_id)
        if row is None:
            raise ProfileNotFoundError("no profile exists for user")
        return _to_profile_out(row)

    # ------------------------------------------------------------- update (PUT §8)
    async def update_profile(
        self, *, user_id: uuid.UUID, profile_id: uuid.UUID, json_resume: dict[str, Any]
    ) -> ProfileOut:
        """PUT /api/profiles/{id} — replaces json_resume; audits ``profile_uploaded`` (D24)."""
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            repo = CoreEngineRepository(db)
            if not await repo.update_profile(user_id, profile_id, json_resume):
                raise ProfileNotFoundError(
                    "profile not found", details={"profile_id": str(profile_id)}
                )
            await ObservabilityRepository(db).insert_audit(
                action="profile_uploaded",
                resource_type="profile",
                resource_id=str(profile_id),
                details={},
            )
            row = await repo.get_profile(user_id, profile_id)
        if row is None:  # pragma: no cover - defensive
            raise ProfileNotFoundError("profile not found", details={"profile_id": str(profile_id)})
        return _to_profile_out(row)