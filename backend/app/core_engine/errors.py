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


class FetchFailedError(CoreEngineError):
    """A Door 1/2/3 fetch was blocked (SSRF/robots) or failed (timeout/transport)."""

    code = "FETCH_FAILED"
    status = 502


class JobNotFoundError(CoreEngineError):
    code = "NOT_FOUND"
    status = 404


class StructuredJDValidationError(CoreEngineError):
    """Door/LLM output failed validation against the structured-JD schema.

    A malformed fixture/API response surfaces as a parse error here, never as
    raw JSON leaking into a snapshot or an API response (S6 §5).
    """

    code = "VALIDATION_ERROR"
    status = 422


class FreshnessBlockedError(CoreEngineError):
    """A posting is no longer fresh enough for the operation that asked for it."""

    code = "JOB_STALE"
    status = 409


class NotAPostingError(CoreEngineError):
    """The URL is not a job posting (D43) — careers-hub/list pages rejected.

    Distinct from a fetch/extraction failure so the API can render the right
    user message ("couldn't identify a job posting") instead of a generic error.
    """

    code = "NOT_A_POSTING"
    status = 422


class ExtractionBudgetExceededError(CoreEngineError):
    """The per-extraction LLM budget tripped (D27 call cap or D45 token cap).

    A coding/expectation error, not a retryable condition: either the cascade
    tried more than the hard 4 + 0–1 section-call ceiling, or the token
    accumulator crossed ``JD_EXTRACTION_TOKEN_BUDGET``.
    """

    code = "EXTRACTION_BUDGET_EXCEEDED"
    status = 429


class ScoringFailedError(CoreEngineError):
    """The evaluation stage of a score failed (D54 single-shot, no retry).

    The rubric may be cached/persisted, but no summary or facet score exists.
    A malformed/refused evaluation response surfaces here (never raw JSON
    leaking into the DB), mirroring D42's no-recall rule.
    """

    code = "SCORING_FAILED"
    status = 500


class RubricGenerationFailedError(CoreEngineError):
    """Rubric generation failed (all providers exhausted or non-JSON output).

    The JD snapshot is untouched and ``rubric_cache`` gets no row: the failure
    is audit-only (errors table), never a partial cache write.
    """

    code = "RUBRIC_GENERATION_FAILED"
    status = 500


class ScoringBudgetExceededError(CoreEngineError):
    """Scoring's hard LLM-call counter tripped (D54).

    Fresh score = 2 routed calls (1 rubric + 1 evaluation); cache-hit re-score
    = 1. Exceeding it is a coding error, same family as S6's
    ``ExtractionBudgetExceededError``.
    """

    code = "SCORING_BUDGET_EXCEEDED"
    status = 429


class NoCurrentProfileError(CoreEngineError):
    """No profile exists for the user (canonical PROFILE_NO_ACTIVE).

    Raised by ``score_job`` when no profile is handed in and the user has no
    rows in ``profiles``; fail-loud before any LLM spend (0 routed calls).
    """

    code = "PROFILE_NO_ACTIVE"
    status = 404


class SnapshotSchemaMismatchError(CoreEngineError):
    """The snapshot payload's schema version is not the current one (D55).

    A fail-loud, ValueError-family guard: ``score_job`` refuses any payload
    whose ``_meta.schema_version != CURRENT_SCHEMA_VERSION`` *before* any LLM
    call — never silently default-filled into a mis-scored shape.
    """

    code = "SNAPSHOT_SCHEMA_MISMATCH"
    status = 422
