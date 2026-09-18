"""0-LLM prompt-injection scan for scoring (D57).

The resume text rendered into the generated criteria template is untrusted, so
before the evaluation call we run ``check_for_prompt_injection`` — the S6
overlap-aware chunk + phrase denylist heuristic — over the text and again over
each line. A flagged result is normalized by dropping the offending lines and,
as a second pass, stripping any remaining denylisted phrase (case-insensitive).

The scan is deliberately **fail-open** (D57): a flagged resume is still scored
with the cleaned text and never triggers a second LLM call, so worst-case cost
stays 1 rubric + 1 evaluation.
"""

from __future__ import annotations

from backend.app.core_engine.jd_extractor import (
    _INJECTION_PATTERNS,
    check_for_prompt_injection,
)


def sanitize_resume_text(text: str) -> tuple[str, bool]:
    """Return ``(cleaned_text, flagged)``.

    ``flagged`` is True when the input tripped the heuristic; ``cleaned_text``
    always has the offending content removed (never re-calls the LLM, D57).
    """
    if not text or not check_for_prompt_injection(text):
        return text, False

    kept = [line for line in text.split("\n") if not check_for_prompt_injection(line)]
    cleaned = "\n".join(kept).strip("\n")

    if check_for_prompt_injection(cleaned):
        cleaned = _strip_denylisted(cleaned)

    return cleaned, True


def _strip_denylisted(text: str) -> str:
    """Strip every known denylisted phrase, case-insensitively (second pass)."""
    lower = text.lower()
    for pattern in _INJECTION_PATTERNS:
        needle = pattern.lower()
        idx = lower.find(needle)
        while idx != -1:
            lower = lower[:idx] + lower[idx + len(needle) :]
            text = text[:idx] + text[idx + len(needle) :]
            idx = lower.find(needle)
    return text.strip("\n")
