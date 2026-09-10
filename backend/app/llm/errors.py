"""LLM router error envelope (§3 of api_contracts/schema.md) and typed errors.

Mirrors ``backend/app/auth/errors.py``: every error carries the canonical ``code``
and the HTTP ``status`` a gateway (S14) would return, plus the documented response
shape (request_id + timestamp) via ``envelope()``. There is no HTTP surface on
llm_router itself (D13) — the service layer raises these; S14 translates them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any


class LlmError(Exception):
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


class ValidationError(LlmError):
    code = "VALIDATION_ERROR"
    status = 422


class ProviderNotFoundError(LlmError):
    code = "PROVIDER_NOT_FOUND"
    status = 404


class ProviderDuplicateError(LlmError):
    code = "PROVIDER_DUPLICATE"
    status = 409


class ProviderTestFailedError(LlmError):
    code = "PROVIDER_TEST_FAILED"
    status = 422


LLM_PROVIDERS_EXHAUSTED = "LLM_PROVIDERS_EXHAUSTED"


class ProvidersExhaustedError(LlmError):
    code = LLM_PROVIDERS_EXHAUSTED
    status = 503
