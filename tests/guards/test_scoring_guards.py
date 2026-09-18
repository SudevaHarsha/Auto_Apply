"""I9 guard — the S7 scoring copies stay attached to their vendored originals.

``test_guards.py::test_vendor_read_only`` pins the vendor *bytes* via
``scripts/vendor.sha256``. This guard pins the *copy* side: the AutoApply
scoring modules must keep the vendored skeleton verbatim so future edits remain
diffable against ``vendor/hiring_agent``. Two documented S7 deltas are allowed
and pinned separately (they are intentional, not drift):

* ``resume_text.py`` renders single-date ``Period:`` lines and adds project
  ``Technologies:``/``Skills:`` (S7 §8).
* ``role.py`` adds a non-vendored ``RoleDefinition``; ``Category`` and the
  vendored field lines stay verbatim.

Math skeleton pinned semantically (``_total_math`` re-structured but identical
expressions); evaluation schemas pinned line-verbatim (``Type``→``type`` alias
is the only allowed token change).
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VENDOR = ROOT / "vendor" / "hiring_agent"
SCORING = ROOT / "backend" / "app" / "core_engine" / "scoring"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _assert_has(source: str, snippet: str, *, where: str = "") -> None:
    assert snippet in source, f"{where}: missing vendored skeleton {snippet!r}"


def test_scoring_resume_text_keeps_vendor_skeleton() -> None:
    ours = _text(SCORING / "resume_text.py")
    vendor = _text(VENDOR / "transform.py")
    for snippet in (
        "def convert_json_resume_to_text(resume_data: JSONResume) -> str:",
        'text_parts.append("=== BASIC INFORMATION ===")',
        "text_parts.append(f\"Name: {basics.name or 'Not provided'}\")",
        "if resume_data.work:",
        "for i, work in enumerate(resume_data.work, 1):",
        "if resume_data.education:",
        "if resume_data.skills:",
        "if resume_data.projects:",
        "if resume_data.awards:",
        "if resume_data.certificates:",
        "if resume_data.publications:",
        "if resume_data.languages:",
        "if resume_data.interests:",
        "if resume_data.references:",
        "if resume_data.volunteer:",
        'return "\\n".join(text_parts)',
    ):
        _assert_has(ours, snippet, where="resume_text.py")
        assert snippet in vendor, f"vendor transform.py drift: {snippet!r}"


def test_scoring_resume_text_single_date_and_project_deltas_pinned() -> None:
    """The documented S7 deltas exist; the unfixed vendor line is gone."""
    ours = _text(SCORING / "resume_text.py")
    _assert_has(ours, "def _render_period(", where="resume_text.py")
    _assert_has(ours, "if project.technologies:", where="resume_text.py")
    _assert_has(ours, "if project.skills:", where="resume_text.py")
    assert 'f"   Period: {work.startDate} - {work.endDate}"' not in ours, (
        "resume_text.py: unfixed vendor Period line leaked in"
    )


def test_scoring_total_math_skeleton() -> None:
    ours = _text(SCORING / "scorer.py")
    for snippet in (
        'min(data["score"], data["max"])',
        'max_score += data["max"]',
        "total += evaluation.bonus_points.total",
        "total -= evaluation.deductions.total",
        "role.bonus_max",
    ):
        _assert_has(ours, snippet, where="scorer.py")


def test_scoring_models_keep_vendor_skeleton() -> None:
    ours = _text(SCORING / "scoring_models.py")
    vendor = _text(VENDOR / "models.py")
    for snippet in (
        "class CategoryScore(BaseModel):",
        'score: float = Field(ge=0, description="Score achieved in this category")',
        'max: int = Field(gt=0, description="Maximum possible score")',
        'evidence: str = Field(min_length=1, description="Evidence supporting the score")',
        "class Deductions(BaseModel):",
        "fields = {category.key: (CategoryScore, ...) for category in categories}",
        'return create_model("Scores", **fields)',
        'Field(ge=0, le=role.bonus_max, description="Total bonus points")',
        '"EvaluationData",',
    ):
        _assert_has(ours, snippet, where="scoring_models.py")
        assert snippet in vendor, f"vendor models.py drift: {snippet!r}"


def test_scoring_role_keeps_vendor_fields() -> None:
    ours = _text(SCORING / "role.py")
    vendor = _text(VENDOR / "roles.py")
    for snippet in (
        "@dataclass(frozen=True)",
        "class Category:",
        "key: str",
        "label: str",
        "max: int",
        "class Role:",
        "position_title: str",
        "bonus_max: int",
        "min_final_score: int",
        "max_final_score: int",
        "criteria_source: str",
        "system_message_source: str",
    ):
        _assert_has(ours, snippet, where="role.py")
        assert snippet in vendor, f"vendor roles.py drift: {snippet!r}"
    _assert_has(vendor, "categories: List[Category]", where="vendor roles.py")
    _assert_has(ours, "categories: list[Category]", where="role.py")


def test_scoring_role_definition_is_autoapply_owned() -> None:
    ours = _text(SCORING / "role.py")
    _assert_has(ours, "class RoleDefinition:", where="role.py")
    _assert_has(ours, "def max_final_score(self) -> int:", where="role.py")
    assert "read_text(encoding=" not in ours, "role.py: vendored role.json file loading must not appear in AutoApply"
