"""Provider-specific JSON-schema dialects (S4/D20 adj, S5).

Pydantic ``model_json_schema()`` output (``$defs``/``$ref``, no
``additionalProperties``) is rejected by every wire provider's structured-output
mode:

- Gemini ``generationConfig.responseSchema``: refuses ``$defs``, ``$ref`` and
  ``additionalProperties`` (unknown-field errors, 400).
- OpenAI-compatible ``response_format.json_schema`` (strict): requires
  ``additionalProperties: false`` on **every** object and all properties listed
  in ``required``; ``$defs``/``$ref`` are not reliably supported.

Each adapter therefore renders the dialect its target accepts. Nothing here
mutates the pydantic models themselves (I9) — the input schema is read-only.
"""

from __future__ import annotations

from typing import Any

_SCALAR_TITLES = frozenset({"title", "description", "default", "$defs"})


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    """Recursively replace ``{"$ref": "#/$defs/X"}`` with the resolved definition."""
    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str) and ref.startswith("#/$defs/"):
            name = ref.rsplit("/", 1)[-1]
            resolved = dict(defs[name])
            return _inline_refs(resolved, defs)
        return {key: _inline_refs(value, defs) for key, value in node.items()}
    if isinstance(node, list):
        return [_inline_refs(item, defs) for item in node]
    return node


def _walk(node: Any, fn) -> Any:
    """Recursively apply ``fn`` to every object node, deepest first."""
    if isinstance(node, dict):
        rebuilt = {key: _walk(value, fn) for key, value in node.items()}
        return fn(rebuilt)
    if isinstance(node, list):
        return [_walk(item, fn) for item in node]
    return node


def gemini_response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini-native ``responseSchema``: refs inlined, no ``additionalProperties``.

    Targets a dialect where every object is structurally explicit and the model
    emits only known fields. Optionality is expressed as ``anyOf`` with
    ``{"type": "null"}`` (which Gemini accepts); ``required`` is left untouched.
    """
    return _walk(_inline_refs(schema, schema.get("$defs", {})), lambda node: _drop(node, ("additionalProperties",)))


def openai_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strict-mode OpenAI JSON-schema: refs inlined, strict objects, all props required."""

    def strictify(node: dict[str, Any]) -> dict[str, Any]:
        node = _drop(node, ("default",))
        props = node.get("properties")
        if isinstance(props, dict):
            node["additionalProperties"] = False
            node["required"] = list(props)
        return node

    return _walk(_inline_refs(schema, schema.get("$defs", {})), strictify)


_drop_keys = frozenset({"$defs"})


def _drop(node: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: value for key, value in node.items() if key not in keys and key not in _drop_keys}