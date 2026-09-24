"""Rubric output + persisted-cache schemas (AutoApply-owned, D49; S7-v2 §B3).

``RubricFacet``/``RubricSchema`` shape the single rubric-generation LLM call
(role.json shape per rubric_generator.md, extended by S7-v2 §B3):

- ``anchors`` (2-5 strictly-ascending bands, 0 → ≤ max) are the score-ladder the
  evaluator applies to each category.
- ``jd_sources`` are *JD references* that anchor the category — either literal
  strings copied from the JD payload (legacy/hybrid) or ``key[i]`` pointers
  resolved server-side to literals before validation (4.1-b). The S7-v2 gate
  (B1/Fix 4) verifies them.
- ``bonus_signals`` name the role-relevant exceptions worth bonus points.
- ``derivation`` is the partition trail: ``scoreable`` (every required skill +
  responsibility that counts toward the score), ``eligibility`` (schedule/shift/
  location/sponsorship — never scored) and ``removed`` (noise with a reason).
  The S7-v2 gate (rubric_generator.validate_partition) is the enforcement layer;
  these fields default so cached v1 envelopes still parse (B4 back-compat).

Wire-safe note (Fix 1/D67): ``min_length``/``pattern``/``exclusiveMinimum`` are
enforced locally by pydantic here and stripped from the wire dialect; constraint
keywords Gemini rejects (``pattern``, ``minLength``, ``exclusiveMinimum``) never
reach a provider schema.

``PersistedRubric`` is the ``rubric_cache.rubric`` JSONB envelope (role.json
fields + rendered criteria / system-message strings, D58) — the exact object
whose deterministic JSON hash is ``rubric_sha256``.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class RubricAnchor(BaseModel):
    """One score-level band in a category's ladder (S7-v2 §B3)."""

    min_points: int = Field(ge=0, description="Minimum points this band describes")
    band: str = Field(min_length=1, description="Description of what earns this score level")


class RubricFacet(BaseModel):
    """One scoring category (role.json shape + S7-v2 §B3 anchors/grounding)."""

    key: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_]+$")
    label: str = Field(min_length=1)
    max: int = Field(gt=0)
    icon: str = "•"
    anchors: list[RubricAnchor] = Field(default_factory=list, description="2-5 ascending score bands, 0 to <= max")
    jd_sources: list[str] = Field(
        default_factory=list,
        description="JD references: key[i] pointers or literal strings (resolved to literals before the gate)",
    )


class DerivationItem(BaseModel):
    """One partition entry (S7-v2 §B3): a signal assigned out of ``scoreable``."""

    field: str = Field(min_length=1, description="The extracted signal text")
    role: Literal["scoreable", "eligibility", "noise"] = "scoreable"
    reason: str = Field(default="", description="Why the item was demoted to eligibility/noise")


class Derivation(BaseModel):
    """The partition trail the S7-v2 gate validates (Fix 4)."""

    scoreable: list[str] = Field(default_factory=list, description="Signals that count toward the score")
    eligibility: list[str] = Field(default_factory=list, description="Hard/flat requirements — never scored")
    removed: list[DerivationItem] = Field(default_factory=list, description="Noise dropped with a reason")


class RubricSchema(BaseModel):
    """The role.json-shaped response a rubric-generation call must produce."""

    position_title: str = Field(min_length=1)
    categories: list[RubricFacet] = Field(min_length=3, max_length=5)
    bonus_max: int = Field(ge=0, le=20)
    bonus_signals: list[str] = Field(default_factory=list, description="Role-relevant exceptional signals worth bonus")
    derivation: Derivation = Field(default_factory=Derivation)


class PersistedRubric(BaseModel):
    """The ``rubric_cache.rubric`` JSONB envelope (D58 + S7-v2 §B3/B4)."""

    name: str
    position_title: str
    categories: list[RubricFacet]
    bonus_max: int = Field(ge=0)
    criteria: str
    system_message: str
    bonus_signals: list[str] = Field(default_factory=list)
    derivation: Derivation = Field(default_factory=Derivation)
    gate_miss: dict[str, Any] | None = Field(default=None, description="Soft-coverage flag from the S7-v2 gate")
