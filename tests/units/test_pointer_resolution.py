"""Fix B (2026-09-25): spaced/dotted ``jd_sources`` pointers resolve, never leak.

4.1 rendered ``key.sub[i]`` index lines verbatim (``other.What You'll Do[0]``)
but ``_POINTER_RE`` only matched ``[A-Za-z_]``-chained identifiers, so a spaced
pointer failed ``_looks_like_pointer`` and fell through as a *literal* — leaking
the raw placeholder into ``jd_sources``. Groq emitted these; gemini happened to
use literals. Fix B loosens the regex to any non-``[`` text; resolution remains
strict (exact ``.``-split key match), so unresolved pointers still fail-loud.
"""

from __future__ import annotations

from backend.app.core_engine.scoring.rubric_generator import _looks_like_pointer, _resolve_pointer

BODY = {
    "responsibilities": ["Own the backend service", "Design and ship REST APIs"],
    "skills": {"required": ["Python", "PostgreSQL"]},
    "other": {"What You'll Do": ["Demo your work to the client weekly"]},
}


def test_spaced_and_apostrophe_key_is_recognized_as_pointer() -> None:
    assert _looks_like_pointer("other.What You'll Do[0]") is True


def test_spaced_pointer_resolves_to_literal() -> None:
    assert _resolve_pointer(BODY, "other.What You'll Do[0]") == "Demo your work to the client weekly"


def test_clean_dotted_pointer_still_resolves() -> None:
    assert _resolve_pointer(BODY, "skills.required[1]") == "PostgreSQL"
    assert _resolve_pointer(BODY, "responsibilities[0]") == "Own the backend service"


def test_out_of_range_spaced_pointer_returns_none() -> None:
    assert _resolve_pointer(BODY, "other.What You'll Do[5]") is None


def test_missing_key_returns_none() -> None:
    assert _resolve_pointer(BODY, "other.No Such Section[0]") is None


def test_literal_text_is_not_a_pointer() -> None:
    assert _looks_like_pointer("Demo your work to the client weekly") is False


def test_scalar_target_is_not_a_pointer_resolution() -> None:
    assert _resolve_pointer({"other": "plain string"}, "other[0]") is None


def test_tradeoff_text_with_bracket_suffix_is_now_pointer_like() -> None:
    """A bare text ending in ``[n]`` now classifies as pointer-like (fail-loud
    direction: it resolves to None -> malformed, never leaks as a literal)."""
    assert _looks_like_pointer("See the full JD[3]") is True
    assert _resolve_pointer(BODY, "See the full JD[3]") is None


BODY_PUNCT = {
    "responsibilities": ["Build features", "Fix bugs"],
    "other": {
        "Why Join Stackbinary?": ["learn fast", "own a slice", "senior review", "live client", "AI tools", "docs"],
    },
}


def test_question_mark_dropped_from_section_key_still_resolves() -> None:
    """4.1-d: Groq emitted ``other.Why Join Stackbinary[3]`` dropping the ``?`` —
    near-match resolution must recover it instead of hard-rejecting."""
    assert _resolve_pointer(BODY_PUNCT, "other.Why Join Stackbinary[3]") == "live client"


def test_exact_key_shortcircuits_before_near_match() -> None:
    assert _resolve_pointer(BODY_PUNCT, "other.Why Join Stackbinary?[5]") == "docs"


def test_apostrophe_drift_still_resolves() -> None:
    assert _resolve_pointer(BODY, "other.What Youll Do[0]") == BODY["other"]["What You'll Do"][0]


def test_below_threshold_similarity_still_fails_loud() -> None:
    """A section so unlike any real key (< 80%) must NOT resolve — invented
    pointers stay hard-rejected, never silently rewired to the wrong section."""
    assert _resolve_pointer(BODY, "other.Completely Unrelated Heading[0]") is None


def test_ambiguous_near_match_tie_still_fails_loud() -> None:
    """Two distinct keys that normalize identically (``A B`` vs ``AB``) must not
    be disambiguated — a tie resolves to None, never a coin-flip wiring."""
    ambiguous = {"A B": ["x"], "AB": ["y"]}
    assert _resolve_pointer(ambiguous, "a b[0]") is None
