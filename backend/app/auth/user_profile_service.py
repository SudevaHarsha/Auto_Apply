"""UserProfileService — GET/PUT /api/auth/user-profile (api_contracts §23).

PUT is an upsert identified by ``user_id``: the first write emits ``user_profile_created``,
subsequent writes ``user_profile_updated``. Column set is whitelisted; any other key is a
validation error. Runs RLS-scoped; the pre-SELECT must therefore happen inside the same
transaction as the write so the "created vs updated" classification holds under FORCE RLS.
"""

from __future__ import annotations

import uuid
from typing import Any

import psycopg

from backend.app.auth.errors import SettingsValueInvalidError, ValidationError
from backend.app.db.context import DbContext
from backend.app.db.repositories.auth_repository import AuthRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository

_SCALAR_FIELDS = {
    "phone",
    "linkedin_url",
    "github_url",
    "website_url",
    "address",
    "city",
    "state",
    "country",
    "postal_code",
    "date_of_birth",
    "gender",
    "ethnicity",
    "veteran_status",
    "disability_status",
    "work_authorization",
}


class UserProfileService:
    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self.conn = conn

    async def get(self, *, user_id: uuid.UUID) -> dict[str, Any] | None:
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            return await AuthRepository(db).get_profile(user_id)

    async def update(self, *, user_id: uuid.UUID, fields: dict[str, Any]) -> dict[str, Any]:
        unknown = [key for key in fields if key not in _SCALAR_FIELDS and key != "custom_fields"]
        if unknown:
            raise ValidationError("unknown profile field", details={"keys": unknown})
        scalars = {key: fields[key] for key in fields if key in _SCALAR_FIELDS}
        custom = fields.get("custom_fields")
        if custom is not None and not isinstance(custom, dict):
            raise SettingsValueInvalidError("custom_fields must be a JSON object", details={"custom_fields": custom})
        inserts = dict(scalars, custom_fields=custom) if custom is not None else scalars

        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            repo = AuthRepository(db)
            existing = await repo.get_profile(user_id) is not None
            if existing:
                await repo.update_profile(user_id, inserts)
            else:
                await repo.insert_profile(user_id, inserts)
            await ObservabilityRepository(db).insert_audit(
                action="user_profile_updated" if existing else "user_profile_created",
                resource_type="user_profile",
                resource_id=user_id,
                details={"fields": sorted(inserts)},
            )
            profile = await repo.get_profile(user_id)
            if profile is None:  # upsert just wrote it; defensive (mypy: dict invariant)
                raise RuntimeError("profile missing after upsert")
            return profile
