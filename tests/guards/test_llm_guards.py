"""S4 guard tests (D14 test-plan row ``guard_no_route_outside_sdk_adapters``).

Provider SDK imports must be confined to ``backend/app/llm/adapters/`` and the
deterministic test double must be physically unreachable from production code.
"""

from __future__ import annotations

import ast
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "backend" / "app"
ADAPTERS = BACKEND / "llm" / "adapters"

_SDK_ROOTS = {"openai", "ollama", "groq", "google"}


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
