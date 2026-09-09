"""auth repository — owns users, api_keys, settings, user_profiles, auth_sessions.

All operations are repo-level (D7): the auth domain's API-key capability is exposed
here only, never as invented HTTP routes. Audit rows are written through the
observability repository's lane, not from this module (ownership guard / I5).
"""

from __future__ import annotations

import datetime as dt
import secrets
import uuid
from typing import Any

from psycopg.types.json import Jsonb

from backend.app.auth.security import sha256_hex
from backend.app.db.repositories.base import BaseRepository

# Canonical register seeds (D11): exactly the two rows api_contracts §7 specifies;
# the remaining defaults are merged at read time (see settings_service.py).
DEFAULT_SETTINGS_SEEDS: dict[str, Any] = {
    "chat_mode": "bot",
    "theme": "dark",
}


def _row(record: tuple[Any, ...] | None, columns: list[str]) -> dict[str, Any] | None:
    if record is None:
        return None
    return {name: value for name, value in zip(columns, record, strict=False)}


_USER_COLUMNS = ["id", "email", "password_hash", "name", "created_at", "updated_at"]


class AuthRepository(BaseRepository):
    """auth owns user identity/credential tables."""

    owns = frozenset({"users", "api_keys", "settings", "user_profiles", "auth_sessions"})

    # ------------------------------------------------------------------ users
    async def create_user(
        self, *, id: uuid.UUID, email: str, password_hash: str, name: str
    ) -> Any:
        """Insert a user with an explicit pre-generated id (D6, FORCE-RLS-safe)."""
        return await self.insert(
            "users",
            {"id": id, "email": email, "password_hash": password_hash, "name": name},
            returning="id",
        )

    async def get_user_by_id(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT id, email, password_hash, name, created_at, updated_at "
            "FROM users WHERE id = %s",
            (str(user_id),),
        )
        return _row(await cur.fetchone(), _USER_COLUMNS)

    async def find_by_email(self, email: str) -> dict[str, Any] | None:
        """D10: SECURITY DEFINER lookup — the only RLS-free path into ``users``."""
        cur = await self.db.execute(
            "SELECT id, email, password_hash, name FROM auth_user_by_email(%s)", (email,)
        )
        return _row(await cur.fetchone(), _USER_COLUMNS[:4])

    # --------------------------------------------------------------- settings
    async def seed_default_settings(self, user_id: uuid.UUID) -> None:
        for key, value in DEFAULT_SETTINGS_SEEDS.items():
            await self.upsert_setting(user_id, key, value)

    async def get_settings(self, user_id: uuid.UUID) -> list[tuple[str, Any, Any]]:
        """Return (key, value, updated_at) rows visible via RLS for ``user_id``."""
        cur = await self.db.execute(
            "SELECT key, value, updated_at FROM settings WHERE user_id = %s",
            (str(user_id),),
        )
        return [(row[0], row[1], row[2]) for row in await cur.fetchall()]

    async def upsert_setting(self, user_id: uuid.UUID, key: str, value: Any) -> None:
        """Upsert one settings row (PK user_id+key); value stored as JSONB."""
        await self.db.execute(
            "INSERT INTO settings (user_id, key, value) VALUES (%s, %s, %s) "
            "ON CONFLICT (user_id, key) DO UPDATE SET value = EXCLUDED.value",
            (str(user_id), key, Jsonb(value)),
        )

    # --------------------------------------------------------------- api keys
    async def create_api_key(
        self, *, user_id: uuid.UUID, name: str, expires_at: dt.datetime | None = None
    ) -> dict[str, Any]:
        """Create an API key; the plaintext secret is returned exactly once (D7/D12)."""
        prefix = "aa_" + secrets.token_hex(6)
        secret = f"{user_id}:{secrets.token_urlsafe(32)}"
        key_hash = sha256_hex(secret)
        key_id = await self.insert(
            "api_keys",
            {
                "user_id": user_id,
                "name": name,
                "prefix": prefix,
                "key_hash": key_hash,
                "expires_at": expires_at,
            },
            returning="id",
        )
        return {
            "id": key_id,
            "name": name,
            "prefix": prefix,
            "key_hash": key_hash,
            "secret": secret,
            "expires_at": expires_at,
        }

    async def find_api_key_by_prefix(self, prefix: str) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT id, user_id, key_hash, prefix, name, last_used_at, expires_at "
            "FROM api_keys WHERE prefix = %s LIMIT 1",
            (prefix,),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        return {
            "id": row[0],
            "user_id": row[1],
            "key_hash": row[2],
            "prefix": row[3],
            "name": row[4],
            "last_used_at": row[5],
            "expires_at": row[6],
        }

    async def revoke_api_key(self, api_key_id: uuid.UUID) -> bool:
        cur = await self.db.execute("DELETE FROM api_keys WHERE id = %s", (str(api_key_id),))
        return cur.rowcount > 0

    async def touch_api_key(self, api_key_id: uuid.UUID) -> None:
        await self.db.execute(
            "UPDATE api_keys SET last_used_at = NOW() WHERE id = %s", (str(api_key_id),)
        )

    # ---------------------------------------------------------- auth_sessions
    async def insert_session(
        self, user_id: uuid.UUID, jti_hash: str, expires_at: dt.datetime
    ) -> Any:
        return await self.insert(
            "auth_sessions",
            {"user_id": user_id, "jti_hash": jti_hash, "expires_at": expires_at},
            returning="id",
        )

    async def revoke_active_session(self, jti_hash: str) -> bool:
        """Atomically revoke one active session row; False if none matched (raced/reused)."""
        cur = await self.db.execute(
            "UPDATE auth_sessions SET revoked_at = NOW() "
            "WHERE jti_hash = %s AND revoked_at IS NULL AND expires_at > NOW()",
            (jti_hash,),
        )
        return cur.rowcount > 0

    async def count_sessions(self, user_id: uuid.UUID) -> int:
        value = await self.db.fetch_scalar(
            "SELECT count(*) FROM auth_sessions WHERE user_id = %s", (str(user_id),)
        )
        return int(value or 0)

    # ---------------------------------------------------------- user_profiles
    async def get_profile(self, user_id: uuid.UUID) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT id, user_id, phone, linkedin_url, github_url, website_url, address, "
            "city, state, country, postal_code, date_of_birth, gender, ethnicity, "
            "veteran_status, disability_status, work_authorization, custom_fields, "
            "created_at, updated_at FROM user_profiles WHERE user_id = %s LIMIT 1",
            (str(user_id),),
        )
        row = await cur.fetchone()
        if row is None:
            return None
        cols = (
            "id", "user_id", "phone", "linkedin_url", "github_url", "website_url",
            "address", "city", "state", "country", "postal_code", "date_of_birth",
            "gender", "ethnicity", "veteran_status", "disability_status",
            "work_authorization", "custom_fields", "created_at", "updated_at",
        )
        return {name: value for name, value in zip(cols, row, strict=False)}

    async def insert_profile(self, user_id: uuid.UUID, fields: dict[str, Any]) -> Any:
        return await self.insert("user_profiles", {"user_id": user_id, **fields}, returning="id")

    async def update_profile(self, user_id: uuid.UUID, fields: dict[str, Any]) -> bool:
        assignments = ", ".join(f"{column} = %s" for column in fields)
        cur = await self.db.execute(
            f"UPDATE user_profiles SET {assignments}, updated_at = NOW() "
            "WHERE user_id = %s",
            [self._dump(v) for v in fields.values()] + [str(user_id)],
        )
        return cur.rowcount > 0