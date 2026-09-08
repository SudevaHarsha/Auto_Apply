"""discord repository — owns discord_connections, discord_messages."""

from __future__ import annotations

from backend.app.db.repositories.base import BaseRepository


class DiscordRepository(BaseRepository):
    """discord owns Discord server/message tables."""

    owns = frozenset({"discord_connections", "discord_messages"})
