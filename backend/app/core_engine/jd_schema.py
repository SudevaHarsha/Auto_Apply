"""Structured JD schema (S6) — the validated shape every snapshot must satisfy.

Own files, not a Firecrawl port. Field set matches the canonical job-description
schema (``docs/components/core_engine/architecture/jd_extractor.md``) plus the
D41 ``good_to_have[]`` field and D44 ``_meta.schema_version``.

Versioning (D44): ``CURRENT_SCHEMA_VERSION`` starts at 1 (ships with
``good_to_have[]`` already present — no snapshots exist before S6, so no
backfill). Every future shape change (field added/renamed/removed) bumps it.
``Meta.schema_version`` is **required** and refuses future values, so a snapshot
written by newer code can never be silently default-flooded into a mis-scored
shape by older readers, and a stale/future-shaped fixture fails loudly.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

CURRENT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class DoorRoute:
    """Door 0 result (``jd_classify.classify_url``).

    ``door`` is the entry door to try: 1 for ATS public APIs (Greenhouse/Lever),
    2 for everything else (JSON-LD → text strip). ``slug`` is the ATS board slug;
    ``job_id`` the optional posting id extracted from the URL.
    """

    url: str
    platform: str
    door: int
    slug: str | None = None
    job_id: str | None = None


@dataclass
class DoorGaps:
    """Which signals the cascade still lacks after a door (D42/D43 bookkeeping)."""

    missing_criticals: list[str] = field(default_factory=list)
    failed_sections: list[str] = field(default_factory=list)

    @property
    def has_criticals(self) -> bool:
        return bool(self.missing_criticals)


class ExperienceRange(BaseModel):
    min_years: float | None = None
    max_years: float | None = None


class SalaryRange(BaseModel):
    min: float | None = None
    max: float | None = None
    currency: str | None = None
    period: str | None = None


class Skills(BaseModel):
    required: list[str] = Field(default_factory=list)
    preferred: list[str] = Field(default_factory=list)


class Education(BaseModel):
    level: str | None = None
    field: str | None = None


class WorkAuthVisa(BaseModel):
    sponsorship: bool | None = None


class Meta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    extracted_via_door: int = 4
    confidence: dict[str, float] | None = None
    schema_version: int
    fetch_engine: str | None = None
    source_url: str | None = None
    extraction_tokens: int | None = None

    @field_validator("schema_version")
    @classmethod
    def _version_not_ahead(cls, version: int) -> int:
        # D44: a snapshot written by a FUTURE shape must never be read as the
        # current shape — fail loudly so the reader migrates deliberately.
        if version > CURRENT_SCHEMA_VERSION:
            raise ValueError(f"snapshot schema_version {version} is ahead of {CURRENT_SCHEMA_VERSION}")
        return version


class StructuredJD(BaseModel):
    """Validated structured job posting (the ``job_snapshots.payload`` shape)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    title: str | None = None
    company: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    experience_range: ExperienceRange | None = None
    salary: SalaryRange | None = None
    skills: Skills = Field(default_factory=Skills)
    education: Education | None = None
    work_auth_visa: WorkAuthVisa | None = None
    responsibilities: list[str] = Field(default_factory=list)
    good_to_have: list[str] = Field(default_factory=list)
    screening_question_hints: list[str] = Field(default_factory=list)
    posted_at: str | None = None
    meta: Meta = Field(alias="_meta")


# ---------------------------------------------------------------------------
# Door 4 section schemas (D41) — one focused ``route_llm_request`` per section.
# Section outputs are merged over the earlier-door fields (see ``merge_over``).
# ---------------------------------------------------------------------------


class HeaderCoreSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str | None = None
    company: str | None = None
    location: str | None = None
    remote_policy: str | None = None
    employment_type: str | None = None
    seniority: str | None = None
    experience_range: ExperienceRange | None = None
    salary: SalaryRange | None = None
    education: Education | None = None
    work_auth_visa: WorkAuthVisa | None = None


class ResponsibilitiesSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    responsibilities: list[str] = Field(default_factory=list)


class SkillsSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    skills: Skills = Field(default_factory=Skills)


class GoodToHaveSection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    good_to_have: list[str] = Field(default_factory=list)
    screening_question_hints: list[str] = Field(default_factory=list)


SECTION_MODELS: dict[str, type[BaseModel]] = {
    "header_core": HeaderCoreSection,
    "responsibilities": ResponsibilitiesSection,
    "skills": SkillsSection,
    "good_to_have": GoodToHaveSection,
}


def _is_empty(value: Any) -> bool:
    """D40: ``None``/``""``/``[]``/``{}`` count as the LLM leaving the field empty."""
    return value is None or (isinstance(value, list | dict | str) and not value)


def merge_over(accumulator: dict[str, Any], section: dict[str, Any]) -> dict[str, Any]:
    """Merge one Door-4 section over the door-1/2 accumulator (D40 semantics).

    The LLM section wins on conflict for its own non-empty fields; LLM-only
    fields are added; fields it left empty (``None``/``""``/``[]``/``{}``) keep
    the earlier-door value. Nested objects are merged shallowly by key
    (``skills``/``experience_range``/``salary``/``education``/``work_auth_visa``),
    also skipping empty inner values (e.g. an all-empty ``skills`` dict never
    clobbers Door 1's ``skills.required``).
    """
    for key, value in section.items():
        if _is_empty(value):
            continue
        if isinstance(value, dict):
            non_empty_inner = {ik: iv for ik, iv in value.items() if not _is_empty(iv)}
            if not non_empty_inner:
                continue
            if isinstance(accumulator.get(key), dict):
                merged = dict(accumulator[key])
                merged.update(non_empty_inner)
                accumulator[key] = merged
            else:
                accumulator[key] = dict(non_empty_inner)
            continue
        accumulator[key] = value
    return accumulator
