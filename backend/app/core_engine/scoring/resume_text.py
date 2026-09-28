"""Resume → plain-text conversion (copied from ``vendor/hiring_agent/transform.py:728-873``, D47).

``convert_json_resume_to_text`` is the vendor function verbatim, with AutoApply
additions that leave the overall shape untouched:

* S7 §8 — single-date ``Period:`` lines for work / education / volunteer /
  projects (a missing start or end date no longer renders ``None - 2024``); and
  ``Technologies:`` / ``Skills:`` lines for projects, whose model already
  carries those fields.
* S8 — LLM-privacy and eval-token cuts: personal identifiers (name, email,
  phone, location), all ``URL`` / ``Website`` / profile links, and every
  education entry except the single highest are omitted from the text sent to
  the LLM. The project ``Skills:`` line stays even when it duplicates
  ``Technologies:`` (both carry the model's native fields).

The vendor file itself stays byte-identical (I9); only this copy is enhanced.
"""

from __future__ import annotations

from typing import Any

from backend.app.core_engine.resume_models import JSONResume


def _render_period(start_date: str | None, end_date: str | None) -> str | None:
    """Render a date range omitting missing dates (S7 resume-goodness)."""
    if start_date and end_date:
        return f"{start_date} - {end_date}"
    if start_date:
        return start_date
    if end_date:
        return end_date
    return None


def _pick_highest_education(education: list[Any]) -> list[Any]:
    """Return only the single most advanced education entry (S8 LLM-privacy).

    Ranked by most recent start date (``YYYY-MM`` compares lexicographically);
    an entry missing a start date falls back to its end date, and a fully
    dateless entry ranks lowest. The remaining education history is omitted
    from the resume text so the LLM only sees the top credential.
    """
    if not education:
        return []
    return [max(education, key=lambda e: e.startDate or e.endDate or "")]


def convert_json_resume_to_text(resume_data: JSONResume) -> str:
    text_parts = []

    if resume_data.basics:
        basics = resume_data.basics
        text_parts.append("=== BASIC INFORMATION ===")

        if basics.summary:
            text_parts.append(f"Summary: {basics.summary}")

        if basics.profiles:
            text_parts.append("Profiles:")
            for profile in basics.profiles:
                text_parts.append(f"  - {profile.network}: {profile.username}")

    if resume_data.work:
        text_parts.append("\n=== WORK EXPERIENCE ===")
        for i, work in enumerate(resume_data.work, 1):
            text_parts.append(f"{i}. {work.position} at {work.name}")
            period = _render_period(work.startDate, work.endDate)
            if period:
                text_parts.append(f"   Period: {period}")
            if work.summary:
                text_parts.append(f"   Description: {work.summary}")
            if work.highlights:
                text_parts.append("   Key Achievements:")
                for highlight in work.highlights:
                    text_parts.append(f"     • {highlight}")

    if resume_data.education:
        text_parts.append("\n=== EDUCATION ===")
        for i, edu in enumerate(_pick_highest_education(resume_data.education), 1):
            text_parts.append(f"{i}. {edu.studyType} in {edu.area}")
            text_parts.append(f"   Institution: {edu.institution}")
            period = _render_period(edu.startDate, edu.endDate)
            if period:
                text_parts.append(f"   Period: {period}")
            if edu.score:
                text_parts.append(f"   Score: {edu.score}")
            if edu.courses:
                text_parts.append(f"   Courses: {', '.join(edu.courses)}")

    if resume_data.skills:
        text_parts.append("\n=== SKILLS ===")
        for skill in resume_data.skills:
            text_parts.append(f"• {skill.name}")
            if skill.level:
                text_parts.append(f"  Level: {skill.level}")
            if skill.keywords:
                text_parts.append(f"  Keywords: {', '.join(skill.keywords)}")

    if resume_data.projects:
        text_parts.append("\n=== PROJECTS ===")
        for i, project in enumerate(resume_data.projects, 1):
            text_parts.append(f"{i}. {project.name}")
            period = _render_period(project.startDate, project.endDate)
            if period:
                text_parts.append(f"   Period: {period}")
            if project.description:
                text_parts.append(f"   Description: {project.description}")
            if project.technologies:
                text_parts.append(f"   Technologies: {', '.join(project.technologies)}")
            if project.skills:
                text_parts.append(f"   Skills: {', '.join(project.skills)}")
            if project.highlights:
                text_parts.append("   Highlights:")
                for highlight in project.highlights:
                    text_parts.append(f"     • {highlight}")

    if resume_data.awards:
        text_parts.append("\n=== AWARDS ===")
        for award in resume_data.awards:
            text_parts.append(f"• {award.title} - {award.awarder} ({award.date})")
            if award.summary:
                text_parts.append(f"  {award.summary}")

    if resume_data.certificates:
        text_parts.append("\n=== CERTIFICATES ===")
        for cert in resume_data.certificates:
            text_parts.append(f"• {cert.name} - {cert.issuer} ({cert.date})")

    if resume_data.publications:
        text_parts.append("\n=== PUBLICATIONS ===")
        for pub in resume_data.publications:
            text_parts.append(f"• {pub.name} - {pub.publisher} ({pub.releaseDate})")
            if pub.summary:
                text_parts.append(f"  {pub.summary}")

    if resume_data.languages:
        text_parts.append("\n=== LANGUAGES ===")
        for lang in resume_data.languages:
            text_parts.append(f"• {lang.language} - {lang.fluency}")

    if resume_data.interests:
        text_parts.append("\n=== INTERESTS ===")
        for interest in resume_data.interests:
            text_parts.append(f"• {interest.name}")
            if interest.keywords:
                text_parts.append(f"  Keywords: {', '.join(interest.keywords)}")

    if resume_data.references:
        text_parts.append("\n=== REFERENCES ===")
        for ref in resume_data.references:
            text_parts.append(f"• {ref.name}")
            if ref.reference:
                text_parts.append(f"  {ref.reference}")

    if resume_data.volunteer:
        text_parts.append("\n=== VOLUNTEER EXPERIENCE ===")
        for volunteer in resume_data.volunteer:
            text_parts.append(f"• {volunteer.position} at {volunteer.organization}")
            period = _render_period(volunteer.startDate, volunteer.endDate)
            if period:
                text_parts.append(f"  Period: {period}")
            if volunteer.summary:
                text_parts.append(f"  Description: {volunteer.summary}")
            if volunteer.highlights:
                text_parts.append("  Highlights:")
                for highlight in volunteer.highlights:
                    text_parts.append(f"    • {highlight}")

    return "\n".join(text_parts)
