"""Output-token limits + input token accounting for scoring steps (4.3, D2).

``estimate_rubric_cap`` / ``estimate_eval_cap`` return the ``max_output_tokens``
a scoring call should send to the provider. The base stays ``BASE_OUTPUT_TOKENS``
(6000); the JD-aware calculation only ever *raises* the cap:

    cap = max(BASE, calc)

Two numbers per call:

- input  = exact tiktoken count of the actually-rendered prompt (+ system) — the
  strings we hand to the provider, so responsibilities/skills content is counted
  through the rendered ``jd_index`` / ``jd_json``, never guessed.
- output = bounded estimate: responsibilities-driven ``echo_pool`` (rubric) or
  scaffolding + allowance (eval), padded by a verbosity allowance.

``budget_expected`` is the D2c check the router uses: ``input + cap`` must fit a
provider's ``tpm`` or the provider is skipped before any call is placed.

Tokenizer: the same lazy ``tiktoken`` cl100k_base the extractor uses; falls back
to a conservative chars/4 estimate when ``tiktoken`` is not installed (labelled
by ``exact`` so callers know whether they are budgeting or guessing).
"""

from __future__ import annotations

import math
import os
from typing import Any

BASE_OUTPUT_TOKENS = 6000
SCAFFOLD_BOUND_RUBRIC = 150
SCAFFOLD_BOUND_EVAL = 400
ALLOWANCE_RUBRIC = 3500
ALLOWANCE_EVAL = 5000
TAIL_SAFETY_FACTOR = 1.10
_CHARS_PER_TOKEN = 4.0

_TOKENIZER: Any = None


def _get_tokenizer() -> Any:
    """Lazily import ``tiktoken`` (safe when the ``jd-render`` extra is absent)."""
    global _TOKENIZER  # noqa: PLW0603
    if _TOKENIZER is not None:
        return _TOKENIZER
    try:  # pragma: no cover - offline CI may lack tiktoken
        import tiktoken  # type: ignore[import-not-found]

        _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    except Exception:
        _TOKENIZER = None
    return _TOKENIZER


def tokens(text: str) -> int:
    """Exact-ish token count: tiktoken when present, chars/4 estimate otherwise."""
    if not text:
        return 0
    tok = _get_tokenizer()
    if tok is not None:
        return len(tok.encode(text))
    return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN))


def _env_allowance(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def _env_absolute_override(name: str, computed: int) -> int:
    """An explicit absolute cap override can only raise the formula value."""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return computed
    try:
        override = max(BASE_OUTPUT_TOKENS, int(raw))
    except ValueError:
        return computed
    return max(computed, override)


def echo_pool_tokens(jd: dict[str, Any]) -> int:
    """JD corpus the rubric may echo back: every responsibility + required skill.

    This is the responsibilities driver: more responsibilities -> larger pool ->
    a larger calculated cap (the base 6000 still holds below it).
    """
    responsibilities = list(jd.get("responsibilities") or [])
    required = list(jd.get("required_skills") or [])
    return sum(tokens(str(item)) for item in responsibilities) + sum(tokens(str(item)) for item in required)


def estimate_rubric_cap(jd: dict[str, Any]) -> int:
    """``max(BASE, echo_pool + scaffold + allowance)`` — JD-aware, base-floored."""
    allowance = _env_allowance("LLM_RUBRIC_ALLOWANCE", ALLOWANCE_RUBRIC)
    calc = echo_pool_tokens(jd) + SCAFFOLD_BOUND_RUBRIC + allowance
    return _env_absolute_override("LLM_MAX_OUTPUT_TOKENS_RUBRIC", max(BASE_OUTPUT_TOKENS, calc))


def estimate_eval_cap(*, resume_tokens: int = 0) -> int:
    """``max(BASE, scaffold + allowance + resume/4)`` for large resumes."""
    allowance = _env_allowance("LLM_EVAL_ALLOWANCE", ALLOWANCE_EVAL)
    calc = SCAFFOLD_BOUND_EVAL + allowance + max(0, resume_tokens // 4)
    return _env_absolute_override("LLM_MAX_OUTPUT_TOKENS_EVAL", max(BASE_OUTPUT_TOKENS, calc))


def count_prompt_tokens(prompt: str, system_message: str | None = None) -> int:
    """Exact input count of the strings actually sent to the provider (D2a)."""
    return tokens(prompt) + tokens(system_message or "")


def budget_expected(prompt_tokens: int, cap_output: int) -> int:
    """``input + cap`` — the D2c number the router budgets a provider against."""
    return prompt_tokens + cap_output


def tail_allowance_from_samples(prose_tail_samples: list[int]) -> int:
    """Self-tuning: P95 of measured prose tails x safety factor (after >=10 samples)."""
    if not prose_tail_samples:
        return 0
    samples = sorted(prose_tail_samples)
    p95_index = max(0, min(len(samples) - 1, math.ceil(0.95 * len(samples)) - 1))
    return int(math.ceil(samples[p95_index] * TAIL_SAFETY_FACTOR))
