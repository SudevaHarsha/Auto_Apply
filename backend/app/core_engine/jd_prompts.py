"""Door 4/5 prompt templates (S6, own prompts — no Firecrawl text ported here).

Section-wise Door 4 (D34/D40/D41) mirrors the S5 per-section pattern from
``core_engine/extraction.py`` (section system message + JSON output + schema),
including the detailed Jinja-template style of the S5 resume prompts: each
Door-4 section renders a ``jd_*.jinja`` template (delimited input block,
per-field JSON skeleton, explicit do/don't rules) and Door 5 renders its own
targeted missing-fields template. Templates live in ``core_engine/templates/``
(.venv ``jd_`` prefix, separate from the S5 resume names) and are rendered
through the same ``TemplateManager``; the inline text below is the fallback —
a template render failure can never hard-fail extraction.

The freshness convention (``Today is: <ISO date>``) follows Firecrawl's
``buildBatchExtractPrompt_F0`` (AGPL-3.0) — the cascade prefers posting-relative
phrases ("5+ years", "ASAP") to resolve cleanly as of the extraction day.
"""

from __future__ import annotations

import os
import re

from backend.app.core_engine.template_manager import TemplateManager

_SECTION_TITLES: dict[str, str] = {
    "header_core": "header / core facts",
    "responsibilities": "day-to-day responsibilities",
    "skills": "required and preferred skills",
    "good_to_have": "nice-to-haves, screening hints, and leftover categories (other)",
}

_SECTION_TEMPLATES: dict[str, str] = {
    "header_core": "jd_header_core",
    "responsibilities": "jd_responsibilities",
    "skills": "jd_skills",
    "good_to_have": "jd_good_to_have",
}

_JD_TEMPLATE_FILES: dict[str, str] = {
    "jd_system_message": "jd_system_message.jinja",
    "jd_header_core": "jd_header_core.jinja",
    "jd_responsibilities": "jd_responsibilities.jinja",
    "jd_skills": "jd_skills.jinja",
    "jd_good_to_have": "jd_good_to_have.jinja",
    "jd_door5_system": "jd_door5_system.jinja",
    "jd_door5": "jd_door5.jinja",
}


class _JdTemplateManager(TemplateManager):
    """TemplateManager subclass that only binds the JD ``jd_*.jinja`` prompts.

    S5-owned ``template_manager.py`` stays untouched (D38 fence); the S5 loader
    is reused for env/config, only the file map is scoped to JD templates.
    """

    def _load_templates(self) -> None:
        self._templates = {}
        for key, filename in _JD_TEMPLATE_FILES.items():
            path = os.path.join(self.template_dir, filename)
            if os.path.exists(path):
                self._templates[key] = self.env.get_template(filename)


_templates = _JdTemplateManager()

_FRESHNESS_LINE = "Today is: {iso_date}"

_SYSTEM_FRAGMENT = (
    "You extract structured facts from a cleaned job-postings text. "
    "Return ONLY a single JSON object — no prose, no markdown fences. "
    "Use only information present in the provided text; set a field to null "
    "when the text does not state it. "
)


def _render(key: str, *, fallback: str, **kwargs: str) -> str:
    """Render a ``jd_*.jinja`` template; fall back verbatim if absent/broken."""
    rendered = _templates.render_template(key, **kwargs)
    return rendered if rendered is not None else fallback


def build_section_system(section: str, now_iso: str) -> str:
    """Per-section system message (S5 pattern); freshness date is injected here."""
    fallback = (
        _SYSTEM_FRAGMENT + f"Extract the section '{_SECTION_TITLES.get(section, section)}' of a job "
        f"posting as the JSON shape below. {_FRESHNESS_LINE.format(iso_date=now_iso)} "
        "Never invent benefits, requirements, or salaries beyond the post."
    )
    return _render(
        "jd_system_message",
        fallback=fallback,
        section_name_param=_SECTION_TITLES.get(section, section),
        iso_date=now_iso,
    )


def build_section_prompt(section: str, cleaned_text: str) -> str:
    """Per-section user prompt; embeds the *trimmed* text Door 4 actually sends."""
    fallback = f"Job postings text:\n\n{cleaned_text}\n\nReturn the {_SECTION_TITLES.get(section, section)} JSON now."
    return _render(
        _SECTION_TEMPLATES.get(section, "jd_header_core"),
        fallback=fallback,
        text_content=cleaned_text,
    )


def build_door5_system(now_iso: str) -> str:
    fallback = (
        _SYSTEM_FRAGMENT + f"Fill ONLY the missing critical fields listed by the caller — nothing "
        f"else. Return a single JSON object with exactly those keys (null if the "
        f"text does not state them). {_FRESHNESS_LINE.format(iso_date=now_iso)}"
    )
    return _render("jd_door5_system", fallback=fallback, iso_date=now_iso)


def build_door5_prompt(cleaned_text: str, missing_criticals: list[str]) -> str:
    safe_missing = [re.sub(r"[^a-z_\-]", "", field) for field in missing_criticals]
    missing_joined = ", ".join(safe_missing) or "(none)"
    fallback = (
        f"Missing critical fields to fill: {missing_joined}. "
        f"Job postings text:\n\n{cleaned_text}\n\n"
        "Return the missing-fields JSON now."
    )
    return _render(
        "jd_door5",
        fallback=fallback,
        text_content=cleaned_text,
        missing_criticals=missing_joined,
    )
