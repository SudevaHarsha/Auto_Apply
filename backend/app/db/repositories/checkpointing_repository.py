"""checkpointing repository — owns checkpoints."""

from __future__ import annotations

from backend.app.db.repositories.base import BaseRepository


class CheckpointingRepository(BaseRepository):
    """checkpointing owns the checkpoint table (pipeline step state)."""

    owns = frozenset({"checkpoints"})
