"""S4 guard tests (D14 test-plan row ``guard_no_route_outside_sdk_adapters``).

Provider SDK imports must be confined to ``backend/app/llm/adapters/`` and the
deterministic test double must be physically unreachable from production code.
The S7-v2 dialect guard (Fix 1/D67) lives here too: whatever constraint keywords
pydantic emits, the wire dialects must never leak the ones Gemini rejects.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend" / "app"
ADAPTERS = BACKEND / "llm" / "adapters"

_SDK_ROOTS = {"openai", "ollama", "groq", "google"}

# The allow-list keys (Fix 1/D67): the schema.JSON implementations may use
# ``exclusiveMaximum``/``pattern``/``min_length`` on every constrained field, but
# Gemini's ``responseSchema`` 400s on them. Nothing outside this set may reach a
# wire schema (they are re-enforced by pydantic ``model_validate`` per consumer).
_RESTRICTED_SCHEMA_KEYWORDS = {
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
}


def test_provider_sdk_imports_confined_to_adapters() -> None:
    violations: list[str] = []
    for py in sorted(BACKEND.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        roots: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.extend(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots.append(node.module.split(".", 1)[0])
        for root in set(roots):
            if root in _SDK_ROOTS and ADAPTERS not in py.parents:
                violations.append(f"{py.relative_to(BACKEND)} imports provider SDK {root!r} outside adapters/")
    assert not violations, "\n".join(violations)


def test_no_test_double_reachable_from_app() -> None:
    hits: list[str] = []
    for py in sorted(BACKEND.rglob("*.py")):
        text = py.read_text(encoding="utf-8")
        if "mock_provider" in text or "MockProvider" in text or "scripted_factory" in text:
            hits.append(str(py.relative_to(BACKEND)))
    assert not hits, "backend/app must never reference the test doubles"


def _schema_keywords(schema: object) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        found.update(_RESTRICTED_SCHEMA_KEYWORDS & set(schema))
        for value in schema.values():
            found.update(_schema_keywords(value))
    elif isinstance(schema, list):
        for value in schema:
            found.update(_schema_keywords(value))
    return found


def test_dialects_allow_list_never_leaks_restricted_keywords() -> None:
    """Fix 1/D67: constrained pydantic models stay wire-safe by construction.

    A rubric/evaluation schema with every constraint family present
    (``gt=max``, ``ge/le``, ``pattern``, ``min_length``) must never surface the
    restricted keywords through either dialect, while the consumer's pydantic
    validation still rejects out-of-range values (enforced locally, not on the
    wire).
    """
    from backend.app.core_engine.scoring.schemas import RubricSchema
    from backend.app.core_engine.scoring.scoring_models import build_evaluation_model
    from backend.app.llm.schema_dialects import gemini_response_schema, openai_compatible_schema

    rubrics_assets = RubricSchema.model_json_schema()
    gemini_rubric = gemini_response_schema(rubrics_assets)
    openai_rubric = openai_compatible_schema(rubrics_assets)
    assert _schema_keywords(gemini_rubric) == set()
    assert _schema_keywords(openai_rubric) == set()

    role = SimpleRole(
        [
            SimpleNamespaceCat("core", "Core", 40),
            SimpleNamespaceCat("skills", "Skills", 30),
            SimpleNamespaceCat("leadership", "Leadership", 20),
        ],
        bonus_max=10,
    )
    evaluation = build_evaluation_model(role)
    gemini_eval = gemini_response_schema(evaluation.model_json_schema())
    openai_eval = openai_compatible_schema(evaluation.model_json_schema())
    assert _schema_keywords(gemini_eval) == set()
    assert _schema_keywords(openai_eval) == set()

    # The fixed/vendor-pinned semantic pins were only *moved*: enforcement still
    # lives in pydantic. The wire forms must still keep the preserved keywords
    # (minimum/maximum are Gemini-legal; pattern/min_length stay local).
    assert "minimum" in _flatten_keys(gemini_rubric)
    assert "maximum" in _flatten_keys(gemini_eval)
    assert "minItems" in _flatten_keys(gemini_eval)  # key_strengths min_items


def _flatten_keys(schema: object) -> set[str]:
    found: set[str] = set()
    if isinstance(schema, dict):
        found.update(schema)
        for value in schema.values():
            found.update(_flatten_keys(value))
    elif isinstance(schema, list):
        for value in schema:
            found.update(_flatten_keys(value))
    return found


class SimpleRole:
    """Minimal stand-in for a RoleDefinition (needs ``categories``/``bonus_max``)."""

    def __init__(self, categories: list[SimpleNamespaceCat], bonus_max: int) -> None:
        self.categories = categories
        self.bonus_max = bonus_max


class SimpleNamespaceCat:
    """Minimal stand-in for a role category with ``key``/``label``/``max``."""

    def __init__(self, key: str, label: str, max: int) -> None:
        self.key = key
        self.label = label
        self.max = max
