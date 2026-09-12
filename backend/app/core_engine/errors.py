"""core_engine error envelope (§5 of api_contracts/schema.md).

Mirrors the auth/llm error pattern: canonical ``code`` and HTTP ``status``
for S14 gateway translation. No HTTP surface on core_engine itself.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any


class CoreEngineError(Exception):
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


class ValidationError(CoreEngineError):
    code = "VALIDATION_ERROR"
    status = 422


class ExtractionFailedError(CoreEngineError):
    code = "EXTRACTION_FAILED"
    status = 500


class ProfileNotFoundError(CoreEngineError):
    code = "NOT_FOUND"
    status = 404
