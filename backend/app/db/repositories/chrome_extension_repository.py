"""chrome_extension repository — owns evidence."""

from __future__ import annotations

from backend.app.db.repositories.base import BaseRepository


class ChromeExtensionRepository(BaseRepository):
    """chrome_extension owns the evidence table (screenshots, PDFs, DOM snapshots, etc.)."""

    owns = frozenset({"evidence"})
