"""discovery repository — owns telegram_connections, telegram_messages."""

from __future__ import annotations

from backend.app.db.repositories.base import BaseRepository


class DiscoveryRepository(BaseRepository):
    """discovery owns Telegram connection + message tables."""

    owns = frozenset({"telegram_connections", "telegram_messages"})
