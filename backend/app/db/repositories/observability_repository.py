"""observability repository — owns audit_logs, error_logs."""

from __future__ import annotations

from backend.app.db.repositories.base import BaseRepository


class ObservabilityRepository(BaseRepository):
    """observability owns audit + error log tables."""

    owns = frozenset({"audit_logs", "error_logs"})
