"""Core-Engine scoring package (S7).

Public surface consumed by the API/package layers and the tests:

* ``score_job`` / ``score_profile`` — score orchestration (D50/D52/D53/D55-D58)
* ``generate_rubric`` — single-call rubric generation (D49/D58)
* ``RoleDefinition`` / ``Category`` — rubric role envelope types
* ``ScoreResult`` / ``RubricFacetScore`` — structured outputs
* ``should_auto_package`` — the normalized 85-gate (D51)
"""

from backend.app.core_engine.scoring.evaluator import ResumeEvaluator
from backend.app.core_engine.scoring.gate import should_auto_package
from backend.app.core_engine.scoring.role import Category, RoleDefinition
from backend.app.core_engine.scoring.rubric_generator import generate_rubric
from backend.app.core_engine.scoring.scorer import RubricFacetScore, ScoreResult, score_job, score_profile

__all__ = [
    "Category",
    "ResumeEvaluator",
    "RoleDefinition",
    "RubricFacetScore",
    "ScoreResult",
    "generate_rubric",
    "score_job",
    "score_profile",
    "should_auto_package",
]
