"""llm_router repository — owns llm_providers, provider_usage, rate_limit_state."""

from __future__ import annotations

from backend.app.db.repositories.base import BaseRepository


class LlmRouterRepository(BaseRepository):
    """llm_router owns provider configuration, usage accounting and rate-limit state."""

    owns = frozenset({"llm_providers", "provider_usage", "rate_limit_state"})
