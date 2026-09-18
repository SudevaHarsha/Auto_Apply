"""Rubric generation (D49/D58, AutoApply-owned — rubric_generator.md).

The JD snapshot payload → exactly one routed LLM call (``json_mode``, role.json
-shaped schema) → an in-memory ``RoleDefinition`` built from the AutoApply
``rubric_generator_*.jinja`` templates (no role-dir filesystem I/O). Missing or
broken templates fall back to inline Jinja constants (still Jinja, never inline
f-strings), so the builders never return None (T7-1).

Persistence (``put_rubric``) is the *scorer's* job: the cache row must land in
the same transaction as the score so a failed score rolls the cache back too
(D56/D58, tests 9x and 10).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

import psycopg
from jinja2 import Environment, FileSystemLoader, Template

from backend.app.core_engine.errors import RubricGenerationFailedError
from backend.app.core_engine.jd_schema import StructuredJD
from backend.app.core_engine.json_utils import extract_json_from_response
from backend.app.llm.router import route_llm_request

from .role import Category, RoleDefinition
from .schemas import PersistedRubric, RubricSchema

_TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "templates")
_ENV = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), trim_blocks=True, lstrip_blocks=True)

_RUBRIC_PROMPT_FALLBACK = """You are building a scoring rubric. Respond with ONLY
top-level JSON object named "rubric":

TITLE: {{ title }}
REQUIRED SKILLS: {{ required_skills }}
REQUIREMENTS: {{ requirements }}
RESPONSIBILITIES: {{ responsibilities }}

{% if mode == "evaluate" %}Evaluate the resume for the {{ position_title }}.

Resume:

{{ text_content }}{% endif %}"""

_RUBRIC_SYSTEM_FALLBACK = """You are an expert technical recruiter.
{% if mode == "evaluate" %}Evaluate candidates for {{ title }} fairly, never using
a candidate's name, gender, institution, or location.{% endif %}"""


def render_template(name: str, *, fallback: str, **kwargs: Any) -> str:
    """Render a rubric_generator template; missing/broken template → inline Jinja fallback.

    Never returns None (T7-1): all build/make helpers funnel through this.
    """
    try:
        template: Template = _ENV.get_template(name)
    except Exception:
        template = _ENV.from_string(fallback)
    try:
        return template.render(**kwargs)
    except Exception:
        return _ENV.from_string(fallback).render(**kwargs)


def jd_summary(payload: dict[str, Any]) -> dict[str, str]:
    """Deterministic JD fields for the generation prompt.

    (rubric_generator.md input contract: title / required_skills / requirements /
    responsibilities.)
    """
    try:
        structured = StructuredJD.model_validate(payload)
    except Exception:
        structured = None

    title = (structured.title if structured and structured.title else payload.get("title")) or "the advertised role"

    if structured:
        skills = structured.skills
        required = list(skills.required)
        preferred = [f"preferred: {item}" for item in skills.preferred]
        required_skills = "; ".join(required + preferred) or "not stated"

        requirement_parts = []
        if structured.education:
            if structured.education.level:
                requirement_parts.append(f"education: {structured.education.level}")
            if structured.education.field:
                requirement_parts.append(f"field: {structured.education.field}")
        if structured.work_auth_visa and structured.work_auth_visa.sponsorship is not None:
            requirement_parts.append(f"visa sponsorship: {'yes' if structured.work_auth_visa.sponsorship else 'no'}")
        if structured.good_to_have:
            requirement_parts.append(f"good to have: {'; '.join(structured.good_to_have[:5])}")
        requirements = "; ".join(requirement_parts) or "not stated"
        responsibilities = "; ".join(structured.responsibilities) or "not stated"
    else:
        skills_raw = (payload.get("skills") or {}) if isinstance(payload, dict) else {}
        required = list(skills_raw.get("required") or [])
        preferred = [f"preferred: {item}" for item in (skills_raw.get("preferred") or [])]
        required_skills = "; ".join(required + preferred) or "not stated"
        requirements = "not stated"
        responsibilities_raw = payload.get("responsibilities") if isinstance(payload, dict) else None
        responsibilities = "; ".join(responsibilities_raw) if isinstance(responsibilities_raw, list) else "not stated"

    return {
        "title": title,
        "required_skills": required_skills,
        "requirements": requirements,
        "responsibilities": responsibilities,
    }


def rubric_sha256(rubric: dict[str, Any]) -> str:
    """Deterministic hash of the persisted rubric envelope (D58 comparison key)."""
    serialized = json.dumps(rubric, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def persist_envelope(role_def: RoleDefinition) -> dict[str, Any]:
    """Envelope written to ``rubric_cache.rubric`` (PersistedRubric shape, D58)."""
    return {
        "name": role_def.name,
        "position_title": role_def.position_title,
        "categories": [
            {"key": cat.key, "label": cat.label, "max": cat.max, "icon": cat.icon} for cat in role_def.categories
        ],
        "bonus_max": role_def.bonus_max,
        "criteria": role_def.criteria,
        "system_message": role_def.system_message,
    }


def build_role_definition(rubric: RubricSchema, *, name: str) -> RoleDefinition:
    """Render the evaluate-mode templates into a ``RoleDefinition`` (D49)."""
    categories = [
        Category(key=cat.key, label=cat.label, max=cat.max, icon=cat.icon or "•") for cat in rubric.categories
    ]
    category_keys = ", ".join(cat.key for cat in rubric.categories)
    criteria = render_template(
        "rubric_generator_prompt.jinja",
        fallback=_RUBRIC_PROMPT_FALLBACK,
        mode="evaluate",
        position_title=rubric.position_title,
        bonus_max=rubric.bonus_max,
        category_keys=category_keys,
        categories=[cat.model_dump() for cat in rubric.categories],
        text_content="{{ text_content }}",
    )
    system_message = render_template(
        "rubric_generator_system.jinja",
        fallback=_RUBRIC_SYSTEM_FALLBACK,
        mode="evaluate",
        title=rubric.position_title,
        category_keys=category_keys,
    )
    return RoleDefinition(
        name=name,
        position_title=rubric.position_title,
        categories=categories,
        bonus_max=rubric.bonus_max,
        criteria=criteria,
        system_message=system_message,
    )


def rebuild_role_definition(data: dict[str, Any]) -> RoleDefinition:
    """Rebuild a ``RoleDefinition`` from a cached envelope (D58 cache-hit path).

    The cached envelope already contains the rendered criteria/system strings, so
    no template re-render happens on a cache hit.
    """
    rubric = PersistedRubric.model_validate(data)
    return RoleDefinition(
        name=rubric.name,
        position_title=rubric.position_title,
        categories=[
            Category(key=cat.key, label=cat.label, max=cat.max, icon=cat.icon or "•") for cat in rubric.categories
        ],
        bonus_max=rubric.bonus_max,
        criteria=rubric.criteria,
        system_message=rubric.system_message,
    )


async def generate_rubric(
    conn: psycopg.AsyncConnection,
    *,
    user_id: uuid.UUID,
    job_id: uuid.UUID,
    snapshot_id: uuid.UUID,
    jd_payload: dict[str, Any],
    adapter_factory: Callable[[str], Any] | None = None,
    before_call: Callable[[], None] | None = None,
) -> tuple[RoleDefinition, str]:
    """Generate + build one rubric for a JD snapshot (exactly 1 routed call, D49).

    ``before_call`` is the scorer's call-counter hook (D54); it runs *before* the
    routed call so a budget refusal propagates as ``ScoringBudgetExceededError``
    and is never swallowed by generation error handling.

    Returns ``(role_def, rubric_sha256)``. A failed/disabled provider chain or an
    unparseable/unvalidated response raises ``RubricGenerationFailedError``.
    """
    summary = jd_summary(jd_payload)
    prompt = render_template(
        "rubric_generator_prompt.jinja",
        fallback=_RUBRIC_PROMPT_FALLBACK,
        mode="generate",
        **summary,
    )
    system_message = render_template(
        "rubric_generator_system.jinja",
        fallback=_RUBRIC_SYSTEM_FALLBACK,
        mode="generate",
        title=summary["title"],
    )

    if before_call is not None:
        before_call()

    try:
        response = await route_llm_request(
            conn,
            user_id=user_id,
            prompt=prompt,
            system_message=system_message,
            json_mode=True,
            output_schema=RubricSchema.model_json_schema(),
            job_id=job_id,
            step="rubric_generation",
            adapter_factory=adapter_factory,
        )
    except Exception as exc:
        raise RubricGenerationFailedError(
            "rubric generation exhausted every configured provider",
            details={"cause": type(exc).__name__},
        ) from exc

    try:
        parsed = json.loads(extract_json_from_response(response.content or ""))
        rubric = RubricSchema.model_validate(parsed)
    except Exception as exc:
        raise RubricGenerationFailedError(
            "rubric generation returned malformed or non-schema output",
            details={"cause": type(exc).__name__, "content_prefix": (response.content or "")[:200]},
        ) from exc

    role_def = build_role_definition(rubric, name=f"job-{job_id}")
    return role_def, rubric_sha256(persist_envelope(role_def))
