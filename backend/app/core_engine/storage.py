"""Local-filesystem storage for uploaded resume PDFs (S5).

Single backend seam for the ``profiles.original_pdf_url`` contract. Every file
path is derived from ``STORAGE_ROOT`` + ``{user_id}/{profile_id}/original.pdf``
so switching to object storage later means changing only this module
(canonical layout: ``/data/profiles/{user_id}/{profile_id}/original.pdf``).
"""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path


def _root() -> str:
    """Resolve STORAGE_ROOT lazily so tests can reconfigure it per-run."""
    return os.environ.get("STORAGE_ROOT", "/data")


def original_pdf_path(user_id: uuid.UUID, profile_id: uuid.UUID) -> Path:
    """Resolve the local path for a profile's original PDF."""
    return Path(_root()) / "profiles" / str(user_id) / str(profile_id) / "original.pdf"


def original_pdf_url(user_id: uuid.UUID, profile_id: uuid.UUID) -> str:
    """Canonical ``original_pdf_url`` string (matches schema.md §8 paths)."""
    return f"/data/profiles/{user_id}/{profile_id}/original.pdf"


def read_pdf(path: str | Path) -> bytes:
    """Read raw PDF bytes for validation/sha256 (Origin path, e.g. multipart temp file)."""
    return Path(path).read_bytes()


def save_pdf(user_id: uuid.UUID, profile_id: uuid.UUID, payload: bytes) -> str:
    """Persist raw PDF bytes under the canonical path; returns the url string."""
    path = original_pdf_path(user_id, profile_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    return original_pdf_url(user_id, profile_id)


def delete_pdf(user_id: uuid.UUID, profile_id: uuid.UUID) -> None:
    """Remove a staged/committed profile directory (rollback + cleanup).

    Also prunes now-empty ancestor directories so an aborted upload leaves no
    staged dirs under STORAGE_ROOT (T5.4).
    """
    path = original_pdf_path(user_id, profile_id).parent
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)
    for parent in (path.parent, path.parent.parent):
        try:
            parent.rmdir()
        except OSError:
            break
