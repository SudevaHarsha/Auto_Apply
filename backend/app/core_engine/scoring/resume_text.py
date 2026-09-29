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
* S8 — third-party identity redaction: no company, employer, volunteer
  organization, school/institute name or referee name is rendered, and any of
  those names — plus the candidate's own name — are masked out of every
  free-text field (summary, descriptions, highlights) they are mentioned in.
  Every link is removed: structured ``url``/``username`` fields are dropped
  entirely and URL-, domain-, email- and phone-shaped strings inside free text
  are masked to ``[redacted]``. Role, dates, degree/area, technologies and
  skills survive, so scoring signal is preserved while identity is not.
* S8 — credential orgs are deliberately KEPT: an award's awarder, a
  certificate's issuer and a publication's publisher are rendered verbatim
  (see ``_with_org``). Those are public, marketable credentials — the brand is
  the signal — unlike an employer or a school, which link one resume to one
  identifiable person.

The vendor file itself stays byte-identical (I9); only this copy is enhanced.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from backend.app.core_engine.resume_models import JSONResume

# --------------------------------------------------------------- redaction ---
_URL_RE = re.compile(r"\b(?:https?://|ftp://|www\.)\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_PHONE_RE = re.compile(r"(?<![\w-])\+?\d[\d\s().-]{6,}\d(?![\w-])")
_ISO_DATE_RE = re.compile(r"\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?")

# A dotted token is only a domain when its last label is a real TLD AND the token
# is not a technology name — "Auro.edu" is redacted, "Node.js" / "ASP.NET" are not.
_TLDS = (
    "com",
    "edu",
    "gov",
    "net",
    "org",
    "io",
    "co",
    "ai",
    "dev",
    "app",
    "me",
    "us",
    "uk",
    "in",
    "xyz",
    "tech",
    "info",
    "biz",
    "online",
    "site",
    "cloud",
)
_DOMAIN_RE = re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:" + "|".join(_TLDS) + r")\b", re.IGNORECASE)
_TECH_TOKENS = frozenset(
    {
        "asp.net",
        "vb.net",
        "node.js",
        "next.js",
        "nuxt.js",
        "vue.js",
        "react.js",
        "express.js",
        "ember.js",
        "backbone.js",
        "three.js",
        "d3.js",
        "chart.js",
        "socket.io",
        "dotnet",
        "w3.org",
        "mozilla.org",
        "npmjs.org",
    }
)

# Legal-entity suffixes: dropped from an alias and swallowed when it trails a
# masked name, so "for Maigha Inc" never leaves "Inc" behind.
_LEGAL_SUFFIXES = (
    "corporation",
    "company",
    "limited",
    "private",
    "holdings",
    "solutions",
    "technologies",
    "technology",
    "corp",
    "inc",
    "llc",
    "ltd",
    "pvt",
    "gmbh",
    "plc",
    "llp",
    "sa",
    "bv",
)
# Generic words that are never a distinguishing name token on their own.
_GENERIC_WORDS = frozenset(
    {
        "media",
        "digital",
        "systems",
        "software",
        "services",
        "service",
        "labs",
        "lab",
        "group",
        "enterprises",
        "industries",
        "international",
        "global",
        "studio",
        "studios",
        "agency",
        "consulting",
        "consultants",
        "partners",
        "ventures",
        "capital",
        "works",
        "the",
        "and",
        "of",
        "college",
        "university",
        "institute",
        "institution",
        "school",
        "academy",
        "polytechnic",
    }
)
_MASK = "[redacted]"


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


def _domain_mask(match: re.Match[str]) -> str:
    token = match.group(0)
    return token if token.lower().rstrip(".") in _TECH_TOKENS else _MASK


def _phone_mask(match: re.Match[str]) -> str:
    """Mask phone-shaped runs, but never an ISO date or a short number."""
    raw = match.group(0)
    if _ISO_DATE_RE.fullmatch(raw.strip()):
        return raw
    digits = re.sub(r"\D", "", raw)
    if not 8 <= len(digits) <= 15:
        return raw
    return _MASK


def _alias_len_ok(alias: str, *, short_acronyms: bool) -> bool:
    """Length gate for one alias.

    >= 4 chars is always masked. A 2-3 char name is masked only when
    ``short_acronyms`` is on AND the token is acronym-shaped (all-caps or
    containing a digit), so ``IBM``/``TCS``/``2U`` go while the lowercase
    English words ``Sun``/``New``/``Air`` survive untouched.
    """
    if len(alias) >= 4:
        return True
    if not short_acronyms or not 2 <= len(alias) <= 3:
        return False
    return alias.isupper() or any(char.isdigit() for char in alias)


def _entity_aliases(name: str, *, include_head: bool, deep: bool = False) -> list[str]:
    """Alias set for one named entity, longest first.

    ``include_head`` adds the leading one/two distinctive tokens so a shortened
    mention in prose ("Maigha Inc" for "Maigha media private limited") is still
    caught. It is off for person names, where the full phrase is the identity.

    ``deep`` widens the rules for employers only, because employer names are the
    ones that routinely reappear in prose in a shortened or acronym form:
    short acronym names (``IBM``, ``TCS``, ``2U``) become maskable, and the
    two-token head is derived from the combined distinctive length so a name
    whose first token is short ("Tata Consultancy") is still caught. Schools,
    awarding bodies and the rest keep the conservative rule set — an institution
    name is not expected in free text, so an exact full-name hit is the safety
    net and no extra surface forms are generated for it.
    """
    words = [w for w in re.split(r"[\s,]+", name.strip()) if w]
    if not words:
        return []
    aliases = {" ".join(words)}
    trimmed = [w for w in words if w.strip(".,").lower() not in _LEGAL_SUFFIXES]
    if trimmed:
        aliases.add(" ".join(trimmed))
    if include_head and words:
        head = words[0].strip(".,")
        head_ok = len(head) >= 5 and head.lower() not in _GENERIC_WORDS
        if head_ok:
            aliases.add(head)
        if len(words) > 1:
            second = words[1].strip(".,")
            pair = f"{head} {second}"
            head_floor = 5 if not deep else 4
            pair_ok = (
                len(head) >= head_floor
                and len(second) >= 3
                and len(pair) >= 8
                and head.lower() not in _GENERIC_WORDS
                and second.lower() not in _GENERIC_WORDS
            )
            if pair_ok:
                aliases.add(pair)
    return sorted(
        (a for a in aliases if a.lower() not in _GENERIC_WORDS and _alias_len_ok(a, short_acronyms=deep)),
        key=len,
        reverse=True,
    )


def _entity_pattern(aliases: list[str]) -> re.Pattern[str]:
    tail = "(?:\\s+(?:" + "|".join(_LEGAL_SUFFIXES) + r")\b\.?)?"
    body = "|".join(re.escape(a) for a in aliases)
    return re.compile(r"(?<![\w-])(?:" + body + ")" + tail + r"(?![\w-])", re.IGNORECASE)


def _protected_terms(resume_data: JSONResume) -> set[str]:
    """Skill/technology strings the candidate is credited with.

    An alias equal to one of these is dropped: a company called "React Media"
    must not erase ``React`` from the skills section.
    """
    terms: set[str] = set()
    for skill in resume_data.skills or []:
        for value in (skill.name, skill.level, *(skill.keywords or [])):
            if value:
                terms.add(value.strip().lower())
    for project in resume_data.projects or []:
        for value in project.technologies or []:
            terms.add(value.strip().lower())
        for value in project.skills or []:
            terms.add(value.strip().lower())
    for work in resume_data.work or []:
        for value in work.highlights or []:
            terms.add(value.strip().lower())
    return terms


def _redactor_for(resume_data: JSONResume) -> Callable[[str], str]:
    """Build the text redactor for one resume (S8 third-party identity redaction).

    Masks links, contact details and every named third party (employer, school,
    awarding body, issuer, publisher, referee) plus the candidate's own name,
    everywhere they appear in the rendered text.
    """
    protected = _protected_terms(resume_data)
    rules: list[tuple[int, re.Pattern[str], str]] = []
    seen: set[str] = set()
    counter = 0

    def add(name: str | None, label: str, *, include_head: bool, deep: bool = False) -> None:
        nonlocal counter
        if not name:
            return
        aliases = [a for a in _entity_aliases(name, include_head=include_head, deep=deep) if a.lower() not in protected]
        if not aliases:
            return
        key = aliases[0].lower()
        if key in seen:
            return
        seen.add(key)
        counter += 1
        rules.append((max(len(alias) for alias in aliases), _entity_pattern(aliases), f"{label} {counter}"))

    # Employers get the deep rule set: their names reappear in prose in
    # shortened ("Maigha Inc") or acronym ("IBM") form far more than any other
    # entity kind, and a miss there leaks the employer straight to the provider.
    for work in resume_data.work or []:
        add(work.name, "Client", include_head=True, deep=True)
    for volunteer in resume_data.volunteer or []:
        add(volunteer.organization, "Organization", include_head=True)
    # Awards/certificates/publications are NOT registered: their awarder, issuer
    # and publisher are kept verbatim in the prompt (see _with_org) because the
    # credential brand is the scoring signal, not an identity leak.
    for edu in resume_data.education or []:
        add(edu.institution, "Institution", include_head=True)
    for ref in resume_data.references or []:
        add(ref.name, "Reference", include_head=False)
    if resume_data.basics:
        add(resume_data.basics.name, "Candidate", include_head=False)

    # Longest alias first: a short alias from one entity must never eat the prefix
    # of a longer name from another (an employer "Sree Venkateswara Systems" and a
    # school "Sree Venkateswara College Of Engeneering" share a head, and applying
    # the short rule first would leave "... Client 1 College Of Engeneering").
    # Python's sort is stable, so equal-specificity rules keep registration order.
    ordered = sorted(rules, key=lambda rule: rule[0], reverse=True)

    def redact(text: str) -> str:
        if not text:
            return text
        out = _EMAIL_RE.sub(_MASK, text)
        out = _URL_RE.sub(_MASK, out)
        out = _DOMAIN_RE.sub(_domain_mask, out)
        out = _PHONE_RE.sub(_phone_mask, out)
        for _specificity, pattern, placeholder in ordered:
            out = pattern.sub(placeholder, out)
        return out

    return redact


def _line(value: str | None, redact: Callable[[str], str], fallback: str = "") -> str:
    cleaned = redact(value).strip() if value else ""
    return cleaned or fallback


def _dated(label: str, date: str | None) -> str:
    """``label (date)`` omitting a missing date (S7: never render ``None``)."""
    return f"{label} ({date})" if date else label


def _with_org(label: str, org: str | None, redact: Callable[[str], str]) -> str:
    """``label - Org`` for the credential-bearing sections (S8).

    An award, a certificate and a publication are marketable credentials: the
    brand that granted or published them *is* the signal ("AWS Solutions
    Architect", "IEEE best paper"), so those org names are deliberately kept in
    the prompt — unlike an employer, a school or a referee, they are a public
    credential rather than a link to one identifiable person.

    The org is still passed through the redactor, so a credential row cannot
    smuggle a URL or an email address back in. An org that happens to be
    registered as one of the candidate's own entities (an award from their
    employer) is still masked — identity wins over credential.
    """
    parts = [part for part in (label, (org or "").strip()) if part]
    return " - ".join(redact(part) for part in parts)


def convert_json_resume_to_text(resume_data: JSONResume) -> str:
    redact = _redactor_for(resume_data)
    text_parts = []

    if resume_data.basics:
        basics = resume_data.basics
        text_parts.append("=== BASIC INFORMATION ===")

        if basics.summary:
            text_parts.append(f"Summary: {redact(basics.summary)}")

        # S8: profile links are dropped entirely — the network type survives, the
        # username/URL (which IS the candidate's identity) never reaches the LLM.
        networks = sorted({p.network.strip() for p in (basics.profiles or []) if p.network and p.network.strip()})
        if networks:
            text_parts.append(f"Profile links: {', '.join(redact(n) for n in networks)}")

    if resume_data.work:
        text_parts.append("\n=== WORK EXPERIENCE ===")
        for i, work in enumerate(resume_data.work, 1):
            text_parts.append(f"{i}. {_line(work.position, redact, 'Role')}")
            period = _render_period(work.startDate, work.endDate)
            if period:
                text_parts.append(f"   Period: {period}")
            if work.summary:
                text_parts.append(f"   Description: {redact(work.summary)}")
            if work.highlights:
                text_parts.append("   Key Achievements:")
                for highlight in work.highlights:
                    text_parts.append(f"     • {redact(highlight)}")

    if resume_data.education:
        text_parts.append("\n=== EDUCATION ===")
        for i, edu in enumerate(_pick_highest_education(resume_data.education), 1):
            text_parts.append(f"{i}. {_line(edu.studyType, redact, 'Program')} in {_line(edu.area, redact, 'Field')}")
            period = _render_period(edu.startDate, edu.endDate)
            if period:
                text_parts.append(f"   Period: {period}")
            if edu.score:
                text_parts.append(f"   Score: {redact(edu.score)}")
            if edu.courses:
                text_parts.append(f"   Courses: {', '.join(redact(c) for c in edu.courses)}")

    if resume_data.skills:
        text_parts.append("\n=== SKILLS ===")
        for skill in resume_data.skills:
            text_parts.append(f"• {redact(skill.name or '')}")
            if skill.level:
                text_parts.append(f"  Level: {redact(skill.level)}")
            if skill.keywords:
                text_parts.append(f"  Keywords: {', '.join(redact(k) for k in skill.keywords)}")

    if resume_data.projects:
        text_parts.append("\n=== PROJECTS ===")
        for i, project in enumerate(resume_data.projects, 1):
            text_parts.append(f"{i}. {redact(project.name or '')}")
            period = _render_period(project.startDate, project.endDate)
            if period:
                text_parts.append(f"   Period: {period}")
            if project.description:
                text_parts.append(f"   Description: {redact(project.description)}")
            if project.technologies:
                text_parts.append(f"   Technologies: {', '.join(redact(t) for t in project.technologies)}")
            if project.skills:
                text_parts.append(f"   Skills: {', '.join(redact(s) for s in project.skills)}")
            if project.highlights:
                text_parts.append("   Highlights:")
                for highlight in project.highlights:
                    text_parts.append(f"     • {redact(highlight)}")

    if resume_data.awards:
        text_parts.append("\n=== AWARDS ===")
        for award in resume_data.awards:
            text_parts.append(f"• {_dated(_with_org(redact(award.title or ''), award.awarder, redact), award.date)}")
            if award.summary:
                text_parts.append(f"  {redact(award.summary)}")

    if resume_data.certificates:
        text_parts.append("\n=== CERTIFICATES ===")
        for cert in resume_data.certificates:
            text_parts.append(f"• {_dated(_with_org(redact(cert.name or ''), cert.issuer, redact), cert.date)}")

    if resume_data.publications:
        text_parts.append("\n=== PUBLICATIONS ===")
        for pub in resume_data.publications:
            text_parts.append(f"• {_dated(_with_org(redact(pub.name or ''), pub.publisher, redact), pub.releaseDate)}")
            if pub.summary:
                text_parts.append(f"  {redact(pub.summary)}")

    if resume_data.languages:
        text_parts.append("\n=== LANGUAGES ===")
        for lang in resume_data.languages:
            text_parts.append(f"• {redact(lang.language or '')} - {redact(lang.fluency or '')}")

    if resume_data.interests:
        text_parts.append("\n=== INTERESTS ===")
        for interest in resume_data.interests:
            text_parts.append(f"• {redact(interest.name or '')}")
            if interest.keywords:
                text_parts.append(f"  Keywords: {', '.join(redact(k) for k in interest.keywords)}")

    if resume_data.references:
        text_parts.append("\n=== REFERENCES ===")
        for i, ref in enumerate(resume_data.references, 1):
            text_parts.append(f"• Reference {i}")
            if ref.reference:
                text_parts.append(f"  {redact(ref.reference)}")

    if resume_data.volunteer:
        text_parts.append("\n=== VOLUNTEER EXPERIENCE ===")
        for volunteer in resume_data.volunteer:
            text_parts.append(f"• {_line(volunteer.position, redact, 'Role')}")
            period = _render_period(volunteer.startDate, volunteer.endDate)
            if period:
                text_parts.append(f"  Period: {period}")
            if volunteer.summary:
                text_parts.append(f"  Description: {redact(volunteer.summary)}")
            if volunteer.highlights:
                text_parts.append("  Highlights:")
                for highlight in volunteer.highlights:
                    text_parts.append(f"    • {redact(highlight)}")

    return "\n".join(text_parts)
