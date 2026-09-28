"""S8/S10 evidence-pointer helpers (evaluator-side, tests/units)."""

import pytest

from backend.app.core_engine.scoring.evaluator import (
    _build_indexed_resume,
    _resolve_evidence_pointers,
)

RESUME = "=== BASIC INFORMATION ===\nSummary: React + Next.js dev\n\n=== SKILLS ===\nKeywords: React, Node"


def test_build_indexed_resume_skips_blank_lines_and_numbers() -> None:
    lines, listing = _build_indexed_resume(RESUME)
    assert lines == [
        "=== BASIC INFORMATION ===",
        "Summary: React + Next.js dev",
        "=== SKILLS ===",
        "Keywords: React, Node",
    ]
    assert "r0 === BASIC INFORMATION ===" in listing
    assert "r1 Summary: React + Next.js dev" in listing
    assert "r3 Keywords: React, Node" in listing
    assert "\n\n" not in listing


def test_resolve_pointers_to_literal_lines() -> None:
    lines, _ = _build_indexed_resume(RESUME)
    resolved = _resolve_evidence_pointers("r1 r3", lines)
    assert resolved == "Summary: React + Next.js dev Keywords: React, Node"


def test_non_pointer_evidence_kept_verbatim() -> None:
    lines, _ = _build_indexed_resume(RESUME)
    assert _resolve_evidence_pointers("no pointers here", lines) == "no pointers here"
    assert _resolve_evidence_pointers("", lines) == ""


def test_out_of_range_pointer_raises() -> None:
    lines, _ = _build_indexed_resume(RESUME)
    with pytest.raises(ValueError):
        _resolve_evidence_pointers("r99", lines)


def test_pointer_syntax_outside_resume_key_is_not_resolved() -> None:
    lines, _ = _build_indexed_resume(RESUME)
    assert _resolve_evidence_pointers("worked on site[3] role", lines) == "worked on site[3] role"
    assert _resolve_evidence_pointers("React and Node", lines) == "React and Node"
