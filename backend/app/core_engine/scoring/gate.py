"""Normalized-score gate (D51)."""

from __future__ import annotations


def should_auto_package(score: int) -> bool:
    """D51: 85-gate on the normalized 0-100 score.

    Pure function — S8/S9 auto-package consumes this directly; a score of exactly
    85 qualifies. The gate is separate from scoring math so the threshold can be
    tuned without touching the normalization.
    """
    return score >= 85
