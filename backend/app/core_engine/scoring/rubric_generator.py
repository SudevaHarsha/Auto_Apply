"""Rubric generation (D49/D58 + S7-v2 §B1/B2/B6 → §10, AutoApply-owned).

The JD snapshot payload → one or two routed LLM calls (``json_mode``, the
extended role.json-shaped schema) → an S7-v2 partition gate → an in-memory
``RoleDefinition`` built from the AutoApply ``rubric_generator_*.jinja``
templates (no role-dir filesystem I/O). Missing or broken templates fall back to
inline Jinja constants (still Jinja, never inline f-strings), so the builders
never return None (T7-1).

S7-v2 corrective design (§10):
- **B1**: the generation prompt carries the *entire structured JD payload*
  (``jd_input``), not a lossy 4-field summary — the gate needs the full corpus
  to verify grounding.
- **Fix 1/D67**: ``RubricSchema.model_json_schema()`` is dialected by
  ``schema_dialects``, which allow-list-strips the wire keywords Gemini rejects;
  pydantic here re-enforces every constraint via ``model_validate``.
- **Fix 2/D68**: provider exhaustion is re-raised **unchanged** (never wrapped
  into ``RubricGenerationFailedError``) so the live skip-guard fires on real
  outages, and the failure is ERROR-logged with attempts/providers.
- **Fix 4**: ``validate_partition`` = hard *grounding* gate (anchors, literal
  ``jd_sources``, ceiling vocabulary, removed-vs-required) + soft
  *self-consistent coverage* gate. A targeted repair runs at most once; a
  grounding failure after repair rejects; a coverage failure after repair
  accepts-with-flag (``gate_miss`` persisted in the envelope + evidence metadata).
- **D71 budget**: rubric ≤ 2 routed calls (1 generation + 1 repair when a gate
  miss runs) + 1 evaluation — the scorer's ``_CallLimiter`` cap is 3. Set
  ``SCORING_DISABLE_RUBRIC_REPAIR=1`` during live testing to force the single-call
  path (no gate repair, saves calls/tokens).

Persistence (``put_rubric``) is the *scorer's* job: the cache row must land in
the same transaction as the score so a failed score rolls the cache back too
(D56/D58, tests 9x and 10).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from jinja2 import Environment, FileSystemLoader, Template

from backend.app.core_engine.errors import RubricGenerationFailedError
from backend.app.core_engine.jd_schema import StructuredJD
from backend.app.core_engine.json_utils import extract_json_from_response
from backend.app.llm.errors import ProvidersExhaustedError
from backend.app.llm.limits import estimate_rubric_cap
from backend.app.llm.router import route_llm_request

from .role import Category, RoleDefinition
from .schemas import PersistedRubric, RubricSchema

logger = logging.getLogger("core_engine.scoring.rubric_generator")

_TEMPLATE_DIR = str(Path(__file__).resolve().parent.parent / "templates")
_ENV = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), trim_blocks=True, lstrip_blocks=True)

_RUBRIC_PROMPT_FALLBACK = """You are building a scoring rubric. Respond with ONLY
top-level JSON object named "rubric":

TITLE: {{ title }}
JOB POSTING listing:
{{ jd_index or jd_json }}

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


def jd_input(payload: dict[str, Any]) -> dict[str, Any]:
    """Deterministic full-payload JD inputs for the generation prompt + gate (B1).

    Returns the full structured JD as a JSON string (``_meta`` excluded so the
    corpus the gate verifies against is the job itself), plus the extracted
    required-skill/responsibility lists the coverage gate needs, plus the
    corpus token set every ``jd_sources``/band claim must trace to.
    """
    structured: StructuredJD | None = None
    try:
        structured = StructuredJD.model_validate(payload)
    except Exception:
        structured = None

    title = (structured.title if structured and structured.title else payload.get("title")) or "the advertised role"

    if structured:
        body = structured.model_dump(exclude={"meta"})
        required = list(structured.skills.required)
        responsibilities = list(structured.responsibilities)
    else:
        body = {key: value for key, value in payload.items() if key != "_meta"}
        skills_raw = (payload.get("skills") or {}) if isinstance(payload, dict) else {}
        required = list(skills_raw.get("required") or [])
        responsibilities_raw = payload.get("responsibilities") if isinstance(payload, dict) else None
        responsibilities = list(responsibilities_raw) if isinstance(responsibilities_raw, list) else []

    jd_json = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {
        "title": title,
        "jd_json": jd_json,
        "jd_body": body,
        "jd_index": _render_indexed_jd(body),
        "required_skills": required,
        "responsibilities": responsibilities,
        "jd_tokens": frozenset(_tokens(jd_json)),
    }


def _render_indexed_jd(body: dict[str, Any]) -> str:
    """Build the single ``key[i]`` pointer cheat-sheet for the generation prompt (4.1-c).

    Renders the *whole* JD exactly once: every array string as ``key.subkey[i]`` /
    ``key[i]`` with visible indices (so the model copies an index instead of
    counting — index off-by-one is the main failure mode this prevents), and every
    scalar leaf (including location/remote_policy/sponsorship/etc.) as
    ``key: value``. This replaces the pre-4.1-c pair of full-JD JSON + separate
    INDEXED REFERENCE block: a single copy guarantees the partition step still sees
    scalars AND kills the duplicated array strings (~700 tokens on the live JD).
    """
    lines: list[str] = []

    def _walk(section: Any, prefix: str) -> None:
        if isinstance(section, list):
            for i, item in enumerate(section):
                if isinstance(item, str):
                    lines.append(f"{prefix}[{i}] {item}")
            return
        if isinstance(section, dict):
            for key, value in section.items():
                _walk(value, f"{prefix}.{key}" if prefix else key)
            return
        if prefix:
            lines.append(f"{prefix}: {section}")

    _walk(body, "")
    if not lines:
        return ""
    return "INDEXED JOB POSTING — every line below is addressable; arrays use `key[i]`:\n" + "\n".join(lines)


def rubric_sha256(rubric: dict[str, Any]) -> str:
    """Deterministic hash of the persisted rubric envelope (D58 comparison key)."""
    serialized = json.dumps(rubric, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def persist_envelope(role_def: RoleDefinition) -> dict[str, Any]:
    """Envelope written to ``rubric_cache.rubric`` (PersistedRubric shape, D58 + §B3)."""
    return {
        "name": role_def.name,
        "position_title": role_def.position_title,
        "categories": [
            {
                "key": cat.key,
                "label": cat.label,
                "max": cat.max,
                "icon": cat.icon,
                "anchors": list(cat.anchors),
                "jd_sources": list(cat.jd_sources),
            }
            for cat in role_def.categories
        ],
        "bonus_max": role_def.bonus_max,
        "bonus_signals": list(role_def.bonus_signals) if role_def.bonus_signals else [],
        "derivation": role_def.derivation or {"scoreable": [], "eligibility": [], "removed": []},
        "gate_miss": role_def.gate_miss,
        "criteria": role_def.criteria,
        "system_message": role_def.system_message,
    }


def _shared_anchor_bands(categories: list[Any]) -> dict[str, Any] | None:
    """If every category has an identical ``(min_points, band)`` ladder, return it
    once as ``{"default_bands": [...], "categories": [...]}`` so the eval prompt
    renders the shared ladder a single time instead of N copies (eval token cut).

    ``categories`` entries are already dicts (``cat.model_dump()``). Returns:
    - ``None`` when categories carry distinct ladders (render each inline).
    - a per-category dict with ``custom_bands=True`` for ladders that differ, so
      the template only prints bands that are actually category-specific.
    """
    if not categories:
        return None
    first = [(a["min_points"], a["band"]) for a in categories[0].get("anchors", [])]
    all_identical = all(
        [(a["min_points"], a["band"]) for a in cat.get("anchors", [])] == first for cat in categories[1:]
    )
    if not all_identical or not first:
        return None
    default_bands = [{"min_points": min_points, "band": band} for min_points, band in first]
    return {"default_bands": default_bands, "custom_bands": False}


def build_role_definition(rubric: RubricSchema, *, name: str) -> RoleDefinition:
    """Render the evaluate-mode templates into a ``RoleDefinition`` (D49 + §B3)."""
    categories = [
        Category(
            key=cat.key,
            label=cat.label,
            max=cat.max,
            icon=cat.icon or "•",
            anchors=[anchor.model_dump() for anchor in cat.anchors],
            jd_sources=list(cat.jd_sources),
        )
        for cat in rubric.categories
    ]
    category_dicts = [cat.model_dump() for cat in rubric.categories]
    shared = _shared_anchor_bands(category_dicts)
    if shared is not None:
        for cat_dict in category_dicts:
            cat_dict["custom_bands"] = False
    else:
        for cat_dict in category_dicts:
            cat_dict["custom_bands"] = True
    category_keys = ", ".join(cat.key for cat in rubric.categories)
    criteria = render_template(
        "rubric_generator_prompt.jinja",
        fallback=_RUBRIC_PROMPT_FALLBACK,
        mode="evaluate",
        position_title=rubric.position_title,
        bonus_max=rubric.bonus_max,
        bonus_signals=rubric.bonus_signals,
        category_keys=category_keys,
        categories=category_dicts,
        default_bands=(shared or {}).get("default_bands"),
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
        bonus_signals=rubric.bonus_signals,
        derivation=rubric.derivation.model_dump() if rubric.derivation else None,
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
            Category(
                key=cat.key,
                label=cat.label,
                max=cat.max,
                icon=cat.icon or "•",
                anchors=[anchor.model_dump() for anchor in cat.anchors],
                jd_sources=list(cat.jd_sources),
            )
            for cat in rubric.categories
        ],
        bonus_max=rubric.bonus_max,
        bonus_signals=rubric.bonus_signals,
        derivation=rubric.derivation.model_dump() if rubric.derivation else None,
        gate_miss=rubric.gate_miss,
        criteria=rubric.criteria,
        system_message=rubric.system_message,
    )


# ============================================================================
# S7-v2 partition gate (Fix 4 / §10.4) — hard grounding + soft coverage.
# ============================================================================

_STOPWORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "at",
        "for",
        "with",
        "as",
        "by",
        "is",
        "are",
        "be",
        "been",
        "am",
        "that",
        "this",
        "these",
        "those",
        "from",
        "into",
        "per",
        "up",
        "out",
        "off",
        "about",
        "over",
        "under",
        "between",
        "within",
        "their",
        "your",
        "our",
        "his",
        "her",
        "its",
        "they",
        "them",
        "we",
        "you",
        "he",
        "she",
        "it",
        "will",
        "would",
        "can",
        "could",
        "should",
        "must",
        "may",
        "might",
        "shall",
        "not",
        "no",
        "do",
        "does",
        "did",
        "have",
        "has",
        "had",
        "was",
        "were",
        "being",
    }
)

_CEILING_VOCAB = frozenset(
    {
        "client",
        "customer",
        "stakeholder",
        "production",
        "prod",
        "ops",
        "operations",
        "operation",
        "incident",
        "incidents",
        "uptime",
        "reliability",
        "sre",
        "pager",
        "sla",
        "call",
        "ownership",
    }
)


def _norm(text: str) -> str:
    return re.sub(r"[^0-9a-z]+", " ", text.casefold()).strip()


def _tokens(text: str) -> frozenset[str]:
    return frozenset(token for token in _norm(text).split() if len(token) > 1 and token not in _STOPWORDS)


@dataclass
class GateResult:
    """S7-v2 partition-gate verdict (§10.4)."""

    hard: list[str] = field(default_factory=list)
    soft: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.hard and not self.soft


def _anchor_lint(rubric: RubricSchema, jd_tokens: frozenset[str]) -> list[str]:
    """Anchor quality lint (upgrade-2 soft checks).

    Soft-only: a lint hit never rejects a rubric outright - it triggers the
    single targeted repair (or ``gate_miss`` when repair is disabled) so the
    operator sees the rubric was coarse, not that it was malformed.

    Checks:
    1. JD grounding - a category's band text must share at least one content
       token with the JD corpus. Purely generic ladders ("no credible evidence
       yet / some evidence, gaps remain / clear evidence matching the JD
       wording") have *zero* JD overlap and deserve a repair pass.
    2. Cross-category duplication - the exact same ``(min_points, band)`` ladder
       on 2+ categories is a copy-pasted rubric, not a per-category score grid.
    3. Binary ladders - exactly two bands at ``{0, max}`` cannot express partial
       credit and push graders to the mid-band; prefer 3+ bands.
    """
    hits: list[str] = []
    seen: dict[tuple[tuple[int, str], ...], str] = {}
    for cat in rubric.categories:
        anchors = list(cat.anchors)
        band_text = frozenset(token for anchor in anchors for token in _tokens(anchor.band))
        if not band_text & jd_tokens:
            hits.append(f"{cat.key}: band text shares no content words with the JD corpus - generic ladder")
        for source in cat.jd_sources:
            source_tokens = _tokens(source)
            if source_tokens and not (source_tokens & jd_tokens):
                hits.append(
                    f"{cat.key}: jd_sources {source!r} resolves to text not in the JD corpus - misgrounded pointer"
                )
        ladder = tuple((anchor.min_points, _norm(anchor.band)) for anchor in anchors)
        if not ladder:
            continue
        if ladder in seen:
            hits.append(f"{cat.key} and {seen[ladder]}: identical anchor ladder on both categories - copy-pasted grid")
        seen[ladder] = cat.key
        points = [anchor.min_points for anchor in anchors]
        if len(points) == 2 and points == sorted([0, cat.max]):
            hits.append(f"{cat.key}: binary 2-band ladder (0/{cat.max}) cannot express partial credit")
    return hits


def validate_partition(rubric: RubricSchema, jd: dict[str, Any]) -> GateResult:
    """The S7-v2 gate: hard grounding (rubric→JD) + soft coverage (JD→rubric).

    Hard (grounding, §10.4A): anchors well-formed, every ``jd_sources`` is a
    literal string present in the JD payload, no band invents ceiling vocabulary
    the payload lacks, and no ``removed`` entry swallows a stated requirement.
    A grounding failure after the single targeted repair REJECTS the rubric.

    Soft (coverage, §10.4B): every required skill and responsibility is assigned
    to a category (scoreable/jd_sources/anchors) or to
    eligibility — matched by normalized content-token overlap, so exact echo is
    not required (D70: extractor pollution to eligibility passes). A coverage
    failure after the repair accepts-with-flag (``gate_miss``).
    """
    result = GateResult()
    jd_tokens: frozenset[str] = jd.get("jd_tokens") or frozenset()
    required = list(jd.get("required_skills") or [])
    responsibilities = list(jd.get("responsibilities") or [])

    for hit in _anchor_lint(rubric, jd_tokens):
        result.soft.append(hit)

    if not rubric.derivation.scoreable:
        result.hard.append("derivation.scoreable must list every scoreable signal")

    for cat in rubric.categories:
        anchors = list(cat.anchors)
        if not (2 <= len(anchors) <= 5):
            result.hard.append(f"{cat.key}: anchors must have 2-5 bands (got {len(anchors)})")
        else:
            points = [anchor.min_points for anchor in anchors]
            if points != sorted(points) or len(set(points)) != len(points):
                result.hard.append(f"{cat.key}: anchors.min_points must be strictly ascending")
            if points[0] != 0:
                result.hard.append(f"{cat.key}: anchors must start at min_points 0")
            if points[-1] > cat.max:
                result.hard.append(f"{cat.key}: top anchor {points[-1]} exceeds max {cat.max}")

        if not cat.jd_sources:
            result.hard.append(f"{cat.key}: jd_sources must be non-empty literal JD strings")
        for source in cat.jd_sources:
            source_tokens = _tokens(source)
            if not source_tokens:
                result.hard.append(f"{cat.key}: jd_sources entry is empty")
            elif not (source_tokens <= jd_tokens):
                result.hard.append(f"{cat.key}: jd_sources {source!r} is not a literal string in the JD payload")

        band_tokens: frozenset[str] = frozenset(token for anchor in anchors for token in _tokens(anchor.band))
        invented = band_tokens & _CEILING_VOCAB - (jd_tokens & _CEILING_VOCAB)
        if invented:
            result.hard.append(
                f"{cat.key}: bands invent ceiling vocabulary {sorted(invented)} not present in the JD payload"
            )

    required_token_sets = [_tokens(item) for item in required]
    for item in rubric.derivation.removed:
        removed_tokens = _tokens(item.field)
        if not removed_tokens:
            continue
        for requirement, requirement_tokens in zip(required, required_token_sets, strict=False):
            if requirement_tokens and removed_tokens <= requirement_tokens:
                result.hard.append(
                    f"removed {item.field!r} swallows required {requirement!r} — requirements stay scoreable"
                )

    anchor_text = " ".join(anchor.band for cat in rubric.categories for anchor in cat.anchors)
    jd_sources_text = " ".join(source for cat in rubric.categories for source in cat.jd_sources)
    category_labels = " ".join(cat.label for cat in rubric.categories)
    scoreable_text = " ".join(rubric.derivation.scoreable)
    rubric_tokens = _tokens(anchor_text) | _tokens(jd_sources_text) | _tokens(category_labels) | _tokens(scoreable_text)
    eligibility_tokens = _tokens(" ".join(rubric.derivation.eligibility))
    assignment_tokens = rubric_tokens | eligibility_tokens

    for requirement in required:
        requirement_tokens = _tokens(requirement)
        if not requirement_tokens:
            continue
        overlap = len(requirement_tokens & assignment_tokens)
        if requirement_tokens <= assignment_tokens or overlap >= max(1, len(requirement_tokens) // 2):
            continue
        result.soft.append(f"required {requirement!r} is not covered by any category or eligibility entry")

    for responsibility in responsibilities:
        responsibility_tokens = _tokens(responsibility)
        if not responsibility_tokens:
            continue
        overlap = len(responsibility_tokens & assignment_tokens)
        if responsibility_tokens <= assignment_tokens or overlap >= 2 or overlap * 2 >= len(responsibility_tokens):
            continue
        result.soft.append(f"responsibility {responsibility!r} is not covered by any category or eligibility entry")

    return result


def _repair_enabled() -> bool:
    """Testing escape hatch: set ``SCORING_DISABLE_RUBRIC_REPAIR=1`` to skip the
    single gate-repair call (S7-v2 §10.4) and save calls/tokens during live runs.

    When disabled, a hard grounding miss rejects immediately with no second call
    and a soft coverage miss accepts-with-flag without regenerating.
    """
    return os.environ.get("SCORING_DISABLE_RUBRIC_REPAIR", "").strip().lower() not in {"1", "true", "yes"}


def _repair_suffix(gate: GateResult) -> str:
    """Targeted repair prompt for the single S7-v2 regeneration (§10.4 A/B)."""
    parts = [
        "Your previous rubric was rejected by the S7-v2 partition gate.",
        "Fix ALL of the problems below and return the COMPLETE revised rubric JSON (same schema, full object):",
    ]
    if gate.hard:
        parts.append("GROUNDING FAILURES (must fix):")
        parts.extend(f"- {item}" for item in gate.hard)
    if gate.soft:
        parts.append("COVERAGE FAILURES (must fix):")
        parts.extend(f"- {item}" for item in gate.soft)
    return "\n\n" + "\n".join(parts)


_POINTER_RE = re.compile(r"^([^\[]+?)\[(\d+)\]$")


def _looks_like_pointer(entry: str) -> bool:
    return _POINTER_RE.match(entry.strip()) is not None


def _resolve_pointer(body: dict[str, Any], pointer: str) -> str | None:
    """Resolve a ``key[i]`` / ``key.sub[i]`` pointer to its literal payload string.

    Mirrors the indexed reference rendered into the prompt (4.1-b rule 3, same
    addressable grammar). Returns ``None`` when the path misses or the target is
    not a string (never returns the raw pointer — an unresolved pointer is a
    malformed-rubric signal, not a pass-through).

    Fix B (2026-09-25): ``_POINTER_RE`` was loosened from chained
    ``[A-Za-z_]`` identifiers to any non-``[`` text (``[^\\[]+?``) so a
    ``key.sub[i]`` line whose segment contains a *space* or apostrophe — e.g.
    ``other.What You'll Do[0]`` — is classified as a pointer (previously it
    failed ``_looks_like_pointer``, fell through as a literal, and leaked the
    raw pointer placeholder into ``jd_sources``). The chain is still split on
    ``.`` with each segment matched exactly against a body key, so resolution
    stays strict and unresolved pointers still fail-loud.
    """
    match = _POINTER_RE.match(pointer.strip())
    if not match:
        return None
    parts = [p for p in match.group(1).split(".")]
    index = int(match.group(2))
    node: Any = body
    for part in parts:
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    if not isinstance(node, list) or index >= len(node):
        return None
    value = node[index]
    return value if isinstance(value, str) else None


def _coerce_rubric(response: Any, *, jd: dict[str, Any]) -> RubricSchema:
    """Parse + strictly validate a rubric-generation response (D49/D55-style).

    Pointer wire format (4.1-b): every ``jd_sources`` entry is either a literal
    JD string (legacy/hybrid back-compat) or a ``key[i]`` pointer that is
    **resolved here, server-side** against the JD body. The gate below never
    sees pointers — it runs on resolved literal text, unchanged. An unresolved
    pointer fails the same as malformed output (no silent pass-through).
    """
    try:
        parsed = json.loads(extract_json_from_response(response.content or ""))
    except Exception as exc:
        raise RubricGenerationFailedError(
            "rubric generation returned malformed or non-schema output",
            details={"cause": type(exc).__name__, "content_prefix": (response.content or "")[:200]},
        ) from exc

    body = jd.get("jd_body") or {}
    if isinstance(parsed, dict):
        for facet in parsed.get("categories") or []:
            if not isinstance(facet, dict):
                continue
            sources = facet.get("jd_sources") or []
            resolved: list[str] = []
            for entry in sources:
                if isinstance(entry, str) and _looks_like_pointer(entry):
                    literal = _resolve_pointer(body, entry)
                    if literal is None:
                        raise RubricGenerationFailedError(
                            "rubric generation returned an unresolvable jd_sources pointer",
                            details={"pointer": entry, "cause": "pointer does not name a string field"},
                        )
                    resolved.append(literal)
                elif isinstance(entry, str):
                    resolved.append(entry)
            facet["jd_sources"] = resolved

    try:
        return RubricSchema.model_validate(parsed)
    except Exception as exc:
        raise RubricGenerationFailedError(
            "rubric generation returned malformed or non-schema output",
            details={"cause": type(exc).__name__, "content_prefix": (response.content or "")[:200]},
        ) from exc


def _flag_gate_miss(gate: GateResult) -> dict[str, Any]:
    return {
        "grounding": list(gate.hard),
        "items": list(gate.soft),
        "repair_used": True,
        "iteration": 2,
    }


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
    """Generate + build one rubric for a JD snapshot (1 or 2 routed calls, D49/D71).

    ``before_call`` is the scorer's call-counter hook (D54/D71); it runs *before*
    each routed call so a budget refusal propagates as
    ``ScoringBudgetExceededError`` and is never swallowed by the generation error
    handling.

    Returns ``(role_def, rubric_sha256)``. Malformed output raises
    ``RubricGenerationFailedError`` after a single call (no retry, D54).
    Provider exhaustion raises ``ProvidersExhaustedError`` **unchanged** so the
    live skip-guard fires (Fix 2/D68). The single gate-repair call runs only when
    ``SCORING_DISABLE_RUBRIC_REPAIR`` is unset/0 (testing escape hatch: hard
    misses reject immediately, soft misses accept-with-flag, one call only). A
    rubric that still fails the hard grounding gate raises
    ``RubricGenerationFailedError``; a soft coverage miss after the repair is
    accepted-with-flag (``role_def.gate_miss``).
    """
    jd = jd_input(jd_payload)
    max_output_tokens = estimate_rubric_cap(jd)
    base_prompt = render_template(
        "rubric_generator_prompt.jinja",
        fallback=_RUBRIC_PROMPT_FALLBACK,
        mode="generate",
        title=jd["title"],
        jd_json=jd["jd_json"],
        jd_index=jd["jd_index"],
    )
    system_message = render_template(
        "rubric_generator_system.jinja",
        fallback=_RUBRIC_SYSTEM_FALLBACK,
        mode="generate",
        title=jd["title"],
    )

    async def _route(prompt: str) -> Any:
        if before_call is not None:
            before_call()
        return await route_llm_request(
            conn,
            user_id=user_id,
            prompt=prompt,
            system_message=system_message,
            json_mode=True,
            output_schema=RubricSchema.model_json_schema(),
            max_output_tokens=max_output_tokens,
            job_id=job_id,
            step="rubric_generation",
            adapter_factory=adapter_factory,
        )

    try:
        response = await _route(base_prompt)
    except ProvidersExhaustedError as exc:
        logger.error(
            "rubric_generation: all providers exhausted",
            extra={
                "data": {
                    "job_id": str(job_id),
                    "step": "rubric_generation",
                    "cause": type(exc).__name__,
                    "attempts": exc.details.get("attempts"),
                    "providers_consumed": exc.details.get("providers_consumed"),
                }
            },
        )
        raise
    except Exception as exc:
        raise RubricGenerationFailedError(
            "rubric generation exhausted every configured provider",
            details={"cause": type(exc).__name__},
        ) from exc

    if response.truncated:
        raise RubricGenerationFailedError(
            "rubric generation output hit its max_output_tokens ceiling",
            details={
                "error_type": "output_truncated",
                "can_continue": True,
                "max_output_tokens": max_output_tokens,
                "completion_tokens": response.completion_tokens,
                "content_prefix": (response.content or "")[:200],
            },
        )

    rubric = _coerce_rubric(response, jd=jd)
    gate = validate_partition(rubric, jd)
    if not gate.passed and _repair_enabled():
        try:
            response = await _route(base_prompt + _repair_suffix(gate))
        except ProvidersExhaustedError as exc:
            logger.error(
                "rubric_generation repair: all providers exhausted",
                extra={
                    "data": {
                        "job_id": str(job_id),
                        "step": "rubric_generation",
                        "cause": type(exc).__name__,
                        "attempts": exc.details.get("attempts"),
                        "providers_consumed": exc.details.get("providers_consumed"),
                    }
                },
            )
            raise
        except Exception as exc:
            raise RubricGenerationFailedError(
                "rubric generation repair exhausted every configured provider",
                details={"cause": type(exc).__name__},
            ) from exc
        if response.truncated:
            raise RubricGenerationFailedError(
                "rubric generation repair output hit its max_output_tokens ceiling",
                details={
                    "error_type": "output_truncated",
                    "can_continue": True,
                    "max_output_tokens": max_output_tokens,
                    "completion_tokens": response.completion_tokens,
                    "content_prefix": (response.content or "")[:200],
                },
            )
        rubric = _coerce_rubric(response, jd=jd)
        gate = validate_partition(rubric, jd)
    if gate.hard:
        logger.error(
            "rubric_generation: rejected by the grounding gate",
            extra={"data": {"job_id": str(job_id), "step": "rubric_generation", "gate": _flag_gate_miss(gate)}},
        )
        raise RubricGenerationFailedError(
            "rubric failed the S7-v2 grounding gate",
            details={"gate": _flag_gate_miss(gate)},
        )

    role_def = build_role_definition(rubric, name=f"job-{job_id}")
    if gate.soft and not gate.hard:
        role_def = RoleDefinition(
            name=role_def.name,
            position_title=role_def.position_title,
            categories=role_def.categories,
            bonus_max=role_def.bonus_max,
            bonus_signals=role_def.bonus_signals,
            derivation=role_def.derivation,
            criteria=role_def.criteria,
            system_message=role_def.system_message,
            gate_miss=_flag_gate_miss(gate),
        )
    return role_def, rubric_sha256(persist_envelope(role_def))
