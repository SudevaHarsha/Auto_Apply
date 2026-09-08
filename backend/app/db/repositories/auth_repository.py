"""auth repository — owns users, api_keys, settings, user_profiles."""

from __future__ import annotations

from backend.app.db.repositories.base import BaseRepository


class AuthRepository(BaseRepository):
    """auth owns user identity/credential tables."""

    owns = frozenset({"users", "api_keys", "settings", "user_profiles"})
