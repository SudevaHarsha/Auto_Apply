"""Scoring role types (copied from ``vendor/hiring_agent/roles.py:22-43``, D47).

``Category`` and ``Role`` are verbatim copies of the vendored frozen dataclasses
(imports rewritten: no vendor tree, no package-relative imports). They are left
in the tree only to anchor the copy lineage; AutoApply's runtime uses
``RoleDefinition`` (D49), which is **not** vendored.

``RoleDefinition`` is the rubric-generator envelope: it carries the *rendered*
evaluation criteria/system prompt strings plus the role.json-shaped fields, and
derives ``max_final_score`` the same way the vendor's ``role.json`` loader does
(sum of category max + bonus_max). S7-v2 §B3/§10.4 extends it with the per-category
``anchors``/``jd_sources``, ``bonus_signals``, the
``derivation`` partition trail and the ``gate_miss`` soft-coverage flag — all
defaulted so v1 builders and cached v1 envelopes still round-trip (B4).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Category:
    """One scoring category and its maximum weight (copied, D47)."""

    key: str
    label: str
    max: int
    icon: str = "•"
    anchors: list = field(default_factory=list)
    jd_sources: list = field(default_factory=list)


@dataclass(frozen=True)
class Role:
    """A fully-loaded role definition (copied from vendor roles.py:32-43, D47)."""

    name: str
    position_title: str
    categories: list[Category]
    bonus_max: int
    min_final_score: int
    max_final_score: int
    criteria_source: str
    system_message_source: str


@dataclass(frozen=True)
class RoleDefinition:
    """Rubric-generator role envelope (D49, AutoApply-owned — not vendored).

    ``criteria`` and ``system_message`` are the *rendered* evaluation prompt
    strings from the AutoApply ``rubric_generator_*.jinja`` templates; the
    evaluator re-renders ``criteria`` with ``text_content`` = resume text
    (vendor ``TemplateManager.render_string`` contract).
    """

    name: str
    position_title: str
    categories: list[Category]
    bonus_max: int
    criteria: str
    system_message: str
    min_final_score: int = 0
    bonus_signals: list = field(default_factory=list)
    derivation: dict | None = None
    gate_miss: dict | None = None

    @property
    def max_final_score(self) -> int:
        """Sum of category max + bonus_max (vendor role.json loader contract)."""
        return sum(cat.max for cat in self.categories) + self.bonus_max
