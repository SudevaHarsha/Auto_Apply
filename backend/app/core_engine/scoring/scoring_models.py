"""Dynamic scoring schemas (copied from ``vendor/hiring_agent/models.py:210-259``, D47).

``CategoryScore``, ``build_scores_model`` and ``build_evaluation_model`` are
verbatim copies — the only rewrite is the ``create_model`` import source
(pydantic in our tree). The generated ``EvaluationData`` is the strict validator
for the evaluation LLM response: missing or extra fields, out-of-range weights
and empty evidence fail loudly and are surfaced as a refused/malformed
evaluation (never silently re-scored).

S7-v2 documented deltas (I9 pins in ``tests/guards/test_scoring_guards.py``):

- ``Deductions`` is **removed** (C1: no opaque penalties — gaps are reported as
  ``critical_gaps`` and hard blockers as ``eligibility.blocked_reasons``).
- ``CategoryScore.evidence_strength`` (0-3) says how directly the quoted
  evidence supports the score (C1).
- ``EvaluationData`` gains ``eligibility`` (``eligible`` + ``blocked_reasons``)
  and ``critical_gaps`` and drops the ``deductions`` field (C1).
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, create_model


class CategoryScore(BaseModel):
    score: float = Field(ge=0, description="Score achieved in this category")
    max: int = Field(gt=0, description="Maximum possible score")
    evidence: str = Field(min_length=1, description="Evidence supporting the score")
    evidence_strength: int = Field(ge=0, le=3, description="How directly the evidence supports the score (0-3)")


class Eligibility(BaseModel):
    """Hard-requirements gate reported alongside the score (S7-v2 C1).

    ``eligible`` stays true unless a hard/flat requirement (schedule, shift,
    location, sponsorship, degree) is clearly unmet; the unmet ones are listed
    in ``blocked_reasons`` and echoed in ``critical_gaps``. It does NOT change
    category math.
    """

    eligible: bool = Field(description="Whether the candidate meets every hard requirement")
    blocked_reasons: list[str] = Field(default_factory=list, description="Unmet hard requirements")


def build_scores_model(categories: Any) -> type[BaseModel]:
    """Build a ``Scores`` model with one ``CategoryScore`` field per category.

    (verbatim, vendor models.py:224-232)
    """
    fields = {category.key: (CategoryScore, ...) for category in categories}
    return create_model("Scores", **fields)  # type: ignore[call-overload]  # (verbatim, vendor 232)


def build_evaluation_model(role: Any) -> type[BaseModel]:
    """Build the strict ``EvaluationData`` model for a role.

    (verbatim, vendor models.py:235-259, minus the removed ``Deductions``)
    """
    scores_model = build_scores_model(role.categories)

    bonus_model = create_model(
        "BonusPoints",
        total=(
            float,
            Field(ge=0, le=role.bonus_max, description="Total bonus points"),
        ),
        breakdown=(str, Field(description="Breakdown of bonus points")),
    )

    return create_model(
        "EvaluationData",
        scores=(scores_model, ...),
        bonus_points=(bonus_model, ...),
        eligibility=(Eligibility, ...),
        critical_gaps=(
            list[str],
            Field(default_factory=list, description="Required skills/conditions the resume is missing"),
        ),  # type: ignore[call-overload]
        key_strengths=(list[str], Field(min_items=1, max_items=5)),  # type: ignore[call-overload]  # verbatim vendor 257
        areas_for_improvement=(list[str], Field(min_items=1, max_items=5)),  # type: ignore[call-overload]  # verbatim vendor 258
    )
