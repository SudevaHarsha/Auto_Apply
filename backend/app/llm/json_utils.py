"""Tolerant LLM JSON parsing (D20 — internal JSON-mode lane).

``parse_llm_json`` extracts a usable JSON value from prompt-written output that is
often wrapped in prose or truncated:

- fenced `` ```json ... ``` `` block extraction (bare fences too),
- single-key wrapper unwrap (``{"result": ...}`` / ``{"output": ...}``),
- balanced-brace/string repair for truncated output,
- trailing prose ignored.

Returns the parsed value or ``None`` when nothing usable is present. No exceptions
escape for malformed input — callers decide attempt semantics (a shape failure is a
*failed attempt*, never a circuit trip, D20).
"""

from __future__ import annotations

import json
import re
from typing import Any

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_WRAPPER_KEYS = ("result", "output")


def _extract_fenced(text: str) -> str | None:
    match = _FENCE_RE.search(text)
    return match.group(1).strip() if match else None


def _unwrap_single_key(value: dict[str, Any]) -> dict[str, Any] | list[Any] | None:
    if len(value) == 1 and next(iter(value)) in _WRAPPER_KEYS and isinstance(value[next(iter(value))], (dict, list)):
        return value[next(iter(value))]
    return None


def _repair_truncated(candidate: str) -> str:
    """Close a truncated JSON document: drop a partial trailing token, then balance"""

    end = len(candidate)
    while end > 0 and candidate[end - 1] in " \t\n\r:,{[`":
        end -= 1
    fixed = candidate[:end]
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in fixed:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in "[{":
            stack.append(ch)
        elif ch in "]}":
            stack and stack.pop()
    if in_string:
        fixed += '"'
    for opening in reversed(stack):
        fixed += "}" if opening == "{" else "]"
    return fixed


def _try_load(candidate: str) -> Any | None:
    try:
        return json.loads(candidate)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None


def _unwrap_wrapper(parsed: Any) -> Any:
    """Unwrap a single-key result/output wrapper; keep the object otherwise."""
    if isinstance(parsed, dict):
        unwrapped = _unwrap_single_key(parsed)
        if unwrapped is not None:
            return unwrapped
    return parsed


def parse_llm_json(text: str) -> Any | None:
    """Return the parsed JSON value, or ``None`` if the text has no usable JSON."""
    if not text or not isinstance(text, str):
        return None
    cleaned = text.strip()
    if not cleaned:
        return None

    candidate = _extract_fenced(text)
    if candidate is not None:
        parsed = _try_load(candidate)
        if parsed is not None:
            return _unwrap_wrapper(parsed)
        repaired = _repair_truncated(candidate)
        parsed = _try_load(repaired)
        if parsed is not None:
            return _unwrap_wrapper(parsed)
        return None

    parsed = _try_load(cleaned)
    if parsed is not None:
        return _unwrap_wrapper(parsed)

    start = cleaned.find("{")
    if start < 0:
        return None
    candidate = cleaned[start:]
    last_close = max(candidate.rfind("}"), candidate.rfind("]"))
    if last_close >= 0:
        candidate = candidate[: last_close + 1]  # drop trailing prose past the closing brace
    repaired = _repair_truncated(candidate)
    parsed = _try_load(repaired)
    if parsed is not None:
        return _unwrap_wrapper(parsed)
    return None
