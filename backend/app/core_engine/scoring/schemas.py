"""Rubric output + persisted-cache schemas (AutoApply-owned, D49).

``RubricFacet``/``RubricSchema`` shape the single rubric-generation LLM call
(role.json shape per rubric_generator.md). ``PersistedRubric`` is the
``rubric_cache.rubric`` JSONB envelope (role.json fields + the rendered criteria /
system-message strings, D58) — the exact object whose deterministic JSON hash is
``rubric_sha256``.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class RubricFacet(BaseModel):
    key: str = Field(min_length=1, pattern=r"^[a-zA-Z0-9_]+$")
    label: str = Field(min_length=1)
    max: int = Field(gt=0)
    icon: str = "•"


class RubricSchema(BaseModel):
    """The role.json-shaped response a rubric-generation call must produce."""

    position_title: str = Field(min_length=1)
    categories: list[RubricFacet] = Field(min_length=3, max_length=5)
    bonus_max: int = Field(ge=0, le=20)


class PersistedRubric(BaseModel):
    """The ``rubric_cache.rubric`` JSONB envelope (D58)."""

    name: str
    position_title: str
    categories: list[RubricFacet]
    bonus_max: int = Field(ge=0)
    criteria: str
    system_message: str
