"""S7-v2 stem-aware ceiling-vocab gate (2026-09-28).

``validate_partition`` rejects bands that invent ceiling vocabulary (production,
ownership, ops, sla, ...) the JD lacks. The ceiling set is fixed, so "stemming"
is an explicit morphological-family table: ``prod``/``production``,
``ownership``/``own``, ``reliability``/``reliable`` resolve to one root and are
accepted, while true inventions (``sla`` against a JD that only says "slack")
stay hard-failed.
"""

from __future__ import annotations

from backend.app.core_engine.scoring.rubric_generator import _CEILING_BY_SURFACE, _ceiling_related, validate_partition
from backend.app.core_engine.scoring.schemas import Derivation, RubricSchema


def _jd(tokens_text: str) -> dict:
    return {
        "jd_tokens": frozenset(tokens_text.split()),
        "required_skills": [],
        "responsibilities": [],
    }


def _rubric(bands: tuple[str, str, str]) -> RubricSchema:
    cats = []
    for idx, words in enumerate(bands):
        cats.append(
            {
                "key": f"cat{idx}",
                "label": f"Cat {idx}",
                "max": 30,
                "icon": "\u2022",
                "anchors": [
                    {"min_points": 0, "band": f"no {words}"},
                    {"min_points": 10, "band": f"some {words}"},
                    {"min_points": 20, "band": f"full {words}"},
                ],
                "jd_sources": ["jdtext"],
            }
        )
    return RubricSchema(
        position_title="T",
        categories=cats,
        bonus_max=0,
        derivation=Derivation(scoreable=["thing"]),
    )


def _invented(gate) -> bool:
    return any("invent ceiling vocabulary" in hit for hit in gate.hard)


def test_every_ceiling_surface_resolves_to_a_root() -> None:
    surfaces = (
        "client",
        "prod",
        "ops",
        "operations",
        "incidents",
        "uptime",
        "reliability",
        "sre",
        "pager",
        "sla",
        "call",
        "ownership",
        "production",
        "customer",
        "stakeholder",
        "operation",
        "incident",
    )
    for surface in surfaces:
        assert surface in _CEILING_BY_SURFACE


def test_prod_accepted_when_jd_says_production() -> None:
    gate = validate_partition(_rubric(("prod", "prod", "prod")), _jd("production incidents"))
    assert not _invented(gate)


def test_ownership_accepted_when_jd_says_own() -> None:
    gate = validate_partition(_rubric(("ownership", "ownership", "ownership")), _jd("own the backend"))
    assert not _invented(gate)


def test_reliability_accepted_when_jd_says_reliable() -> None:
    gate = validate_partition(_rubric(("reliability", "reliability", "reliability")), _jd("reliable systems"))
    assert not _invented(gate)


def test_plural_accepted_via_shared_root() -> None:
    gate = validate_partition(_rubric(("incidents", "incidents", "incidents")), _jd("incident naming"))
    assert not _invented(gate)


def test_sla_still_rejected_against_lookalike_slack() -> None:
    gate = validate_partition(_rubric(("sla", "sla", "sla")), _jd("slack python flask"))
    assert _invented(gate)


def test_true_invention_still_hard_failed() -> None:
    gate = validate_partition(_rubric(("sla", "uptime", "ownership")), _jd("python api flask"))
    assert _invented(gate)


def test_out_of_family_surface_never_grounds() -> None:
    assert _ceiling_related("slack", frozenset({"sla"})) is False


def test_surface_in_family_grounds_against_its_root() -> None:
    assert _ceiling_related("ownership", frozenset({"ownership"})) is True
