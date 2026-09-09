"""Auth error envelope (§3 of api_contracts/schema.md) and typed service errors.

Each error carries the canonical ``code`` and the HTTP ``status`` a gateway (S14)
would return. ``envelope()`` renders the documented response shape (request_id +
timestamp) so T3 can assert it without any router being mounted.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any


class AuthError(Exception):
    """Base error with canonical code and HTTP status."""

    code: str
    status: int

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def envelope(self) -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "request_id": str(uuid.uuid4()),
                "timestamp": datetime.now(UTC).isoformat(),
            }
        }


class ValidationError(AuthError):
    code = "VALIDATION_ERROR"
    status = 422


class UserExistsError(AuthError):
    code = "AUTH_USER_EXISTS"
    status = 409


class WeakPasswordError(AuthError):
    code = "AUTH_WEAK_PASSWORD"
    status = 400


class InvalidCredentialsError(AuthError):
    code = "AUTH_INVALID_CREDENTIALS"
    status = 401


class TokenExpiredError(AuthError):
    code = "AUTH_TOKEN_EXPIRED"
    status = 401


class TokenInvalidError(AuthError):
    code = "AUTH_TOKEN_INVALID"
    status = 401


class SettingsKeyInvalidError(AuthError):
    code = "SETTINGS_KEY_INVALID"
    status = 400


class SettingsValueInvalidError(AuthError):
    code = "SETTINGS_VALUE_INVALID"
    status = 422


class PermissionDeniedError(AuthError):
    code = "FORBIDDEN"
    status = 403