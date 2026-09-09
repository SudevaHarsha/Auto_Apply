"""JWT + password security primitives (D8, D12).

Bearer transport only (no cookie in the API contract); access tokens live 15 min,
refresh tokens 7 days; refresh tokens carry a random ``jti`` whose hash — never the
raw value — is persisted in ``auth_sessions``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import os
import re
import uuid
from typing import Any

import bcrypt
import jwt

from backend.app.auth.errors import TokenExpiredError, TokenInvalidError, WeakPasswordError

ACCESS_TTL = dt.timedelta(minutes=15)
REFRESH_TTL = dt.timedelta(days=7)
ACCESS_TYPE = "access"
REFRESH_TYPE = "refresh"

_PASSWORD_POLICY = re.compile(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^\w\s]).{8,}$")


def jwt_secret() -> str:
    """HS256 signing secret; required at app start, never logged."""
    value = os.getenv("JWT_SECRET")
    if not value:
        raise RuntimeError("JWT_SECRET is required but not set")
    return value


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str, *, dummy: bool = False) -> bool:
    """Constant-ish check; ``dummy`` equalizes latency when no row exists (anti-enumeration)."""
    if dummy:
        bcrypt.checkpw(password.encode(), bcrypt.hashpw(b"dummy", bcrypt.gensalt()))
        return False
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def check_password_policy(password: str) -> None:
    if not _PASSWORD_POLICY.match(password):
        raise WeakPasswordError(
            "password must be 8+ chars with an upper, lower, digit, and special char"
        )


def _encode(payload: dict[str, Any], ttl: dt.timedelta) -> str:
    now = dt.datetime.now(dt.UTC)
    signed = {**payload, "iat": now, "exp": now + ttl}
    return jwt.encode(signed, jwt_secret(), algorithm="HS256")


def create_access_token(user_id: uuid.UUID, email: str) -> str:
    return _encode({"sub": str(user_id), "email": email, "typ": ACCESS_TYPE}, ACCESS_TTL)


def create_refresh_token(user_id: uuid.UUID) -> tuple[str, str]:
    jti = str(uuid.uuid4())
    token = _encode({"sub": str(user_id), "jti": jti, "typ": REFRESH_TYPE}, REFRESH_TTL)
    return token, jti


def decode_token(token: str, *, expected_type: str) -> dict[str, Any]:
    """Decode + verify HS256 signature and required claims; enforce ``typ`` separation."""
    try:
        payload = jwt.decode(
            token,
            jwt_secret(),
            algorithms=["HS256"],
            options={"require": ["sub", "iat", "exp", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenExpiredError("token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenInvalidError("invalid or malformed token") from exc
    if payload.get("typ") != expected_type:
        raise TokenInvalidError(f"token type must be {expected_type!r}")
    if not payload.get("sub"):
        raise TokenInvalidError("token missing subject")
    return payload


def sha256_hex(content: str) -> str:
    return hashlib.sha256(content.encode()).hexdigest()