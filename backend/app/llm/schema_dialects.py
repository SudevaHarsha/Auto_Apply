"""Provider-specific JSON-schema dialects (S4/D20 adj, S5; Fix 1/D67).

Pydantic ``model_json_schema()`` output (``$defs``/``$ref``, no
``additionalProperties``, plus ``exclusiveMinimum``/``pattern``/``minLength``
from constrained fields) is rejected by every wire provider's structured-output
mode:

- Gemini ``generationConfig.responseSchema``: refuses ``$defs``, ``$ref``,
  ``additionalProperties``, ``exclusiveMinimum``, ``pattern`` and ``minLength``
  (unknown-field / "Cannot find field" 400s).
- OpenAI-compatible ``response_format.json_schema`` (strict): requires
  ``additionalProperties: false`` on **every** object and all properties listed
  in ``required``; ``$defs``/``$ref`` are not reliably supported.

Each adapter therefore renders the dialect its target accepts. Nothing here
mutates the pydantic models themselves (I9) — the input schema is read-only.

**Fix 1 / D67 — allow-list, not deny-list:** every past bug was a *missing entry
on a deny-list* (``exclusiveMinimum`` shipped because only ``$defs``/
``additionalProperties`` were stripped). The transforms here are allow-lists:
any future constrained field adds a keyword that the wire silently drops, while
the pydantic ``model_validate`` step in each consumer re-enforces the real
constraint locally — so a stripped keyword can never re-break a provider.
"""

from __future__ import annotations

from typing import Any

# Keys both dialects understand on the wire. Everything else (notably
# ``exclusiveMinimum``, ``exclusiveMaximum``, ``pattern``, ``format``,
# ``minLength``, ``maxLength``, ``minProperties``, ``maxProperties``, ``$defs``,
# ``$ref``, ``title``) is dropped below — pydantic enforces it after parse.
_ALLOWED_WIRE_KEYS = frozenset(
    {
        "type",
        "enum",
        "default",
        "description",
        "items",
        "properties",
        "required",
        "anyOf",
        "minimum",
        "maximum",
        "minItems",
        "maxItems",
    }
)

# Keywords that are legal pydantic output but must never reach a provider wire
# schema. Used by ``_transform`` to recognize schema objects even when a node
# carries nothing but stripped keywords (e.g. a lone ``{"minLength": 7}``).
_RESTRICTED_WIRE_KEYS = frozenset(
    {
        "exclusiveMinimum",
        "exclusiveMaximum",
        "pattern",
        "format",
        "minLength",
        "maxLength",
        "minProperties",
        "maxProperties",
        "$defs",
        "$ref",
        "title",
    }
)


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


def _allow_list(node: dict[str, Any]) -> dict[str, Any]:
    """Strip every schema keyword outside the wire allow-list (Fix 1/D67)."""
    return {key: value for key, value in node.items() if key in _ALLOWED_WIRE_KEYS}


def _transform(node: Any, fn) -> Any:
    """Transform every *schema object* in a ref-inlined pydantic JSON schema.

    Only dicts whose keys are schema keywords are treated as schema objects and
    pass through ``fn`` (the allow-list / strictify). Name-keyed maps such as
    ``properties`` and ``$defs`` are traversed but not filtered themselves —
    otherwise their property names (e.g. ``position_title``) would be stripped
    and ``properties`` would collapse to ``{}`` (regression caught by the
    allow-list guard).
    """
    if isinstance(node, list):
        return [_transform(item, fn) for item in node]
    if not isinstance(node, dict):
        return node
    is_schema = any(key in _ALLOWED_WIRE_KEYS or key in _RESTRICTED_WIRE_KEYS for key in node)
    node = fn(node) if is_schema else node
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in ("properties", "$defs") and isinstance(value, dict):
            result[key] = {name: _transform(schema, fn) for name, schema in value.items()}
        elif key in ("items", "additionalProperties") and isinstance(value, dict):
            result[key] = _transform(value, fn)
        elif key in ("anyOf", "oneOf", "allOf", "prefixItems") and isinstance(value, list):
            result[key] = [_transform(item, fn) for item in value]
        else:
            result[key] = value
    return result


def gemini_response_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Gemini-native ``responseSchema``: refs inlined, allow-list filtered.

    ``additionalProperties`` is dropped (it is not in the allow-list); optionality
    stays as ``anyOf`` with ``{"type": "null"}`` (which Gemini accepts);
    ``required`` is left untouched. Constraint keywords Gemini would 400 on
    (``exclusiveMinimum``, ``pattern``, ``minLength``, ...) are stripped here and
    re-enforced by the consumer's pydantic ``model_validate``.
    """
    return _transform(_inline_refs(schema, schema.get("$defs", {})), _allow_list)


def openai_compatible_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Strict-mode OpenAI JSON-schema: refs inlined, allow-list + strict objects."""

    def strictify(node: dict[str, Any]) -> dict[str, Any]:
        node = _allow_list(node)
        props = node.get("properties")
        if isinstance(props, dict):
            node["additionalProperties"] = False
            node["required"] = list(props)
        return node

    return _transform(_inline_refs(schema, schema.get("$defs", {})), strictify)
