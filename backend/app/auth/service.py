"""AuthService — register / login / refresh / logout / me (api_contracts §7).

Stateless orchestrator over AuthRepository + ObservabilityRepository. Each operation
opens its own ``DbContext.transaction()`` scoped to the identity the operation is for
(register: the pre-generated id; login/refresh/logout/me: the authenticated subject).
No HTTP dependency: callers (S14 gateway) supply the connection; ``ip_address`` is
optional and passed through to the audit lane.
"""

from __future__ import annotations

import datetime as dt
import ipaddress
import uuid
from dataclasses import dataclass

import psycopg

from backend.app.auth.errors import (
    InvalidCredentialsError,
    TokenInvalidError,
    UserExistsError,
    ValidationError,
)
from backend.app.auth.security import (
    ACCESS_TTL,
    ACCESS_TYPE,
    REFRESH_TTL,
    REFRESH_TYPE,
    check_password_policy,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    sha256_hex,
    verify_password,
)
from backend.app.db.context import DbContext
from backend.app.db.repositories.auth_repository import AuthRepository
from backend.app.db.repositories.observability_repository import ObservabilityRepository


@dataclass(frozen=True)
class AuthResult:
    id: uuid.UUID
    email: str
    name: str
    access_token: str
    refresh_token: str
    expires_in: int = int(ACCESS_TTL.total_seconds())


@dataclass(frozen=True)
class RefreshResult:
    access_token: str
    refresh_token: str
    expires_in: int = int(ACCESS_TTL.total_seconds())


@dataclass(frozen=True)
class UserOut:
    id: uuid.UUID
    email: str
    name: str
    created_at: dt.datetime


def _email_is_valid(email: str) -> bool:
    return "@" in email and "." in email.split("@")[-1] and not email.startswith("@")


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def _session_expiry() -> dt.datetime:
    return _now_utc() + REFRESH_TTL


class AuthService:
    def __init__(self, conn: psycopg.AsyncConnection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------ register
    async def register(
        self,
        *,
        email: str,
        password: str,
        name: str,
        ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None,
    ) -> AuthResult:
        email = (email or "").strip().lower()
        if not _email_is_valid(email):
            raise ValidationError("invalid email address", details={"email": email})
        if not name or not name.strip():
            raise ValidationError("name is required")
        # Password strength checked here (WeakPasswordError/400) before any write.
        check_password_policy(password)
        user_id = uuid.uuid4()  # D6: pre-generated explicit id lets register pass FORCE RLS.
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            repo = AuthRepository(db)
            if await repo.find_by_email(email):
                raise UserExistsError("email is already registered", details={"email": email})
            await repo.create_user(
                id=user_id,
                email=email,
                password_hash=hash_password(password),
                name=name,
            )
            await repo.seed_default_settings(user_id)  # D11: exactly chat_mode + theme
            await ObservabilityRepository(db).insert_audit(
                action="user_registered",
                resource_type="user",
                resource_id=user_id,
                details={"email": email},
                ip_address=ip_address,
            )
            access = create_access_token(user_id, email)
            refresh, jti = create_refresh_token(user_id)
            await repo.insert_session(user_id, sha256_hex(jti), _session_expiry())
        return AuthResult(id=user_id, email=email, name=name, access_token=access, refresh_token=refresh)

    # --------------------------------------------------------------------- login
    async def login(
        self,
        *,
        email: str,
        password: str,
        ip_address: ipaddress.IPv4Address | ipaddress.IPv6Address | None = None,
    ) -> AuthResult:
        email = (email or "").strip().lower()
        # Lookup runs in an isolated anonymous transaction (definer function bypasses RLS);
        # a missing row triggers a dummy bcrypt compare so timing does not leak existence.
        async with DbContext(self.conn, user_id=None).transaction() as lookup:
            identity = await AuthRepository(lookup).find_by_email(email)
        if identity is None:
            verify_password("", "dummy", dummy=True)
            raise InvalidCredentialsError("invalid email or password", details={"email": email})
        if not verify_password(password, identity["password_hash"]):
            raise InvalidCredentialsError("invalid email or password", details={"email": email})
        user_id = identity["id"]
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            repo = AuthRepository(db)
            access = create_access_token(user_id, identity["email"])
            refresh, jti = create_refresh_token(user_id)
            await repo.insert_session(user_id, sha256_hex(jti), _session_expiry())
            await ObservabilityRepository(db).insert_audit(
                action="user_logged_in",
                resource_type="user",
                resource_id=user_id,
                ip_address=ip_address,
            )
        return AuthResult(
            id=user_id,
            email=identity["email"],
            name=identity["name"],
            access_token=access,
            refresh_token=refresh,
        )

    # -------------------------------------------------------------------- refresh
    async def refresh(self, *, refresh_token: str) -> RefreshResult:
        payload = decode_token(refresh_token, expected_type=REFRESH_TYPE)
        user_id = uuid.UUID(payload["sub"])
        jti = payload.get("jti")
        if not jti:
            raise TokenInvalidError("refresh token missing jti")
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            repo = AuthRepository(db)
            # Rotation (D8): the presented session is revoked atomically; reuse finds no
            # active row and is rejected.
            if not await repo.revoke_active_session(sha256_hex(jti)):
                raise TokenInvalidError("refresh token already used or revoked")
            identity = await repo.get_user_by_id(user_id)
            if identity is None:
                raise TokenInvalidError("user no longer exists")
            access = create_access_token(user_id, identity["email"])
            refresh, new_jti = create_refresh_token(user_id)
            await repo.insert_session(user_id, sha256_hex(new_jti), _session_expiry())
        return RefreshResult(access_token=access, refresh_token=refresh)

    # --------------------------------------------------------------------- logout
    async def logout(self, *, refresh_token: str) -> None:
        """Revoke the presented session server-side (D9). Already-revoked/expired tokens
        are idempotent no-ops; nothing is audited for logout."""
        payload = decode_token(refresh_token, expected_type=REFRESH_TYPE)
        user_id = uuid.UUID(payload["sub"])
        jti = payload.get("jti")
        if not jti:
            raise TokenInvalidError("refresh token missing jti")
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            await AuthRepository(db).revoke_active_session(sha256_hex(jti))

    # ------------------------------------------------------------------------- me
    async def me(self, *, access_token: str) -> UserOut:
        payload = decode_token(access_token, expected_type=ACCESS_TYPE)
        user_id = uuid.UUID(payload["sub"])
        db = DbContext(self.conn, user_id=user_id)
        async with db.transaction():
            identity = await AuthRepository(db).get_user_by_id(user_id)
        if identity is None:
            raise TokenInvalidError("user no longer exists")
        return UserOut(
            id=user_id,
            email=identity["email"],
            name=identity["name"],
            created_at=identity["created_at"],
        )
