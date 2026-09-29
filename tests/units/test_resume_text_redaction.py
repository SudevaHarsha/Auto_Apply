"""S8 LLM-prompt redaction: no identity, no links (tests/units).

The resume text built here is the ONLY candidate payload that leaves the system,
so every assertion below is a privacy assertion on the eval prompt.
"""

from __future__ import annotations

from typing import Any

from backend.app.core_engine.resume_models import JSONResume
from backend.app.core_engine.scoring.resume_text import (
    _entity_aliases,
    _redactor_for,
    convert_json_resume_to_text,
)

PAYLOAD: dict[str, Any] = {
    "basics": {
        "name": "Sudeva Harsha Gummidela",
        "email": "gummidela.sudeva@gmail.com",
        "phone": "+91 63052 68835",
        "url": "https://sudevaharsha-protfolio.onrender.com/",
        "location": {"city": "Nellore", "region": "AP", "countryCode": "IN"},
        "summary": (
            "Frontend engineer at Auro.edu shipping React.js and Next.js. "
            "Previously with Maigha media private limited. "
            "Mail me at gummidela.sudeva@gmail.com or call +91 63052 68835. "
            "See https://github.com/SudevaHarsha and www.linkedin.com/in/sudeva-harsha-718906255."
        ),
        "profiles": [
            {
                "network": "LinkedIn",
                "username": "sudeva-harsha-718906255",
                "url": "https://www.linkedin.com/in/sudeva-harsha-718906255",
            },
            {"network": "GitHub", "username": "SudevaHarsha", "url": "https://github.com/SudevaHarsha"},
            {"network": "Portfolio", "username": None, "url": "https://portfolio.example.com"},
        ],
    },
    "work": [
        {
            "name": "Maigha media private limited",
            "position": "Web Developer",
            "url": "https://maigha.example.com",
            "startDate": "2024-10",
            "endDate": "2024-12",
            "summary": "Shipped a navigation module for Maigha Inc with 3 interns.",
            "highlights": [
                "Improved performance 20% at Maigha",
                "Used Node.js, Express.js and ASP.NET Core",
            ],
        },
        {
            "name": "React Media Labs",
            "position": "Junior Web Developer",
            "startDate": "2024-01",
            "endDate": "2024-03",
            "summary": "Led 5 interns on a booking system for a garden-events client.",
            "highlights": ["Real-time availability checks"],
        },
    ],
    "education": [
        {
            "institution": "Sree Venkateswara College Of Engeneering",
            "url": "https://svce.example.edu",
            "area": "Computer Science and Engineering",
            "studyType": "Bachelor of Technology",
            "startDate": "2021-11",
            "endDate": "2025-04",
            "score": "82.1%",
            "courses": ["Data Structures"],
        }
    ],
    "volunteer": [
        {
            "organization": "Nellore Robotics Club",
            "position": "Mentor",
            "url": "https://nrc.example.org",
            "startDate": "2023-06",
            "endDate": "2023-12",
            "summary": "Mentored 12 students at the club.",
            "highlights": ["Ran weekly workshops"],
        }
    ],
    "awards": [{"title": "Best Debugger", "date": "2024-02", "awarder": "Maigha media private limited"}],
    "certificates": [{"name": "AWS Cloud Practitioner", "date": "2024-05", "issuer": "Amazon Web Services"}],
    "publications": [
        {
            "name": "Scaling React Apps",
            "publisher": "Springer",
            "releaseDate": "2023-08",
            "url": "https://link.springer.example/article/1",
            "summary": "Peer-reviewed chapter.",
        }
    ],
    "references": [
        {
            "name": "Ravi Kumar",
            "reference": "Manager at Maigha media private limited, mail ravi.kumar@corp.example.com",
        },
    ],
    "projects": [
        {
            "name": "Discord Clone",
            "description": "Real-time chat clone; live at https://discord-clone.example.dev, docs at docs.example.io.",
            "technologies": ["Next.js", "Node.js", "ASP.NET"],
            "skills": ["Node.js", "Prisma"],
            "highlights": ["Cut latency 40%"],
        }
    ],
    "skills": [
        {
            "name": "Web Development",
            "level": "Advanced",
            "keywords": ["React", "Node.js", "Express.js", "Next.js", "ASP.NET", "MongoDB"],
        }
    ],
    "languages": [{"language": "English", "fluency": "Fluent"}],
    "interests": [{"name": "Cricket", "keywords": ["T20"]}],
}

IDENTITY_TOKENS = (
    "Sudeva",
    "Harsha",
    "Gummidela",
    "gummidela.sudeva@gmail.com",
    "63052",
    "68835",
    "718906255",
    "linkedin.com",
    "github.com",
    "onrender.com",
    "Auro.edu",
    "Maigha",
    "React Media",
    "Sree Venkateswara",
    "Nellore",
    "Nellore Robotics",
    "Amazon Web Services",
    "Springer",
    "Ravi Kumar",
    "ravi.kumar@corp.example.com",
    "example.dev",
    "docs.example.io",
    "discord-clone.example.dev",
    "svce.example.edu",
)

SIGNAL_TOKENS = (
    "Web Developer",
    "Bachelor of Technology",
    "Computer Science and Engineering",
    "2024-10 - 2024-12",
    "2021-11 - 2025-04",
    "82.1%",
    "Node.js",
    "Express.js",
    "ASP.NET",
    "Next.js",
    "MongoDB",
    "React",
    "Mentor",
    "Best Debugger",
    "AWS Cloud Practitioner",
    "Scaling React Apps",
    "Data Structures",
    "20%",
    "12 students",
)


def _text() -> str:
    return convert_json_resume_to_text(JSONResume.model_validate(PAYLOAD))


def test_no_identity_or_link_survives_into_the_prompt() -> None:
    text = _text().lower()
    leaked = [token for token in IDENTITY_TOKENS if token.lower() in text]
    assert not leaked, f"identity/link leaked into the eval prompt: {leaked}"


def test_named_third_parties_in_prose_become_placeholders() -> None:
    text = _text()
    assert "Client 1" in text  # "Maigha media private limited" mentioned in prose
    assert "Profile links: GitHub, LinkedIn, Portfolio" in text


def test_named_third_parties_in_structured_fields_are_not_rendered() -> None:
    """A name that only ever appears in a structured field is simply dropped."""
    text = _text()
    assert "• Mentor" in text  # volunteer position kept, organization dropped
    assert "• AWS Cloud Practitioner" in text  # certificate issuer dropped
    assert "• Scaling React Apps" in text  # publisher dropped
    assert "• Reference 1" in text  # referee name dropped
    assert "Organization 1" not in text
    assert "Issuer 1" not in text
    assert "Publisher 1" not in text


def test_legal_suffix_is_swallowed_not_left_behind() -> None:
    text = _text()
    assert "module for Client 1 with 3 interns" in text, text
    assert " Inc" not in text


def test_education_line_keeps_degree_but_drops_institution() -> None:
    text = _text()
    assert "1. Bachelor of Technology in Computer Science and Engineering" in text
    assert "Institution:" not in text


def test_scoring_signal_survives_redaction() -> None:
    text = _text()
    missing = [token for token in SIGNAL_TOKENS if token not in text]
    assert not missing, f"redaction destroyed scoring signal: {missing}"


def test_iso_dates_and_numbers_are_not_mistaken_for_contacts() -> None:
    text = _text()
    assert "2024-10 - 2024-12" in text
    assert "2021-11 - 2025-04" in text
    assert "82.1%" in text
    assert "[redacted]" in text  # something was actually masked


def test_company_name_matching_a_skill_never_erases_the_skill() -> None:
    """A company called "React Media" must not delete ``React`` from skills."""
    text = _text()
    assert "Keywords: React, Node.js" in text
    assert "React Media" not in text


def test_missing_dates_do_not_render_none() -> None:
    payload = {
        "basics": {"name": "X Y"},
        "awards": [{"title": "Winner"}],
        "work": [{"name": "Acme", "position": "Engineer"}],
    }
    text = convert_json_resume_to_text(JSONResume.model_validate(payload))
    assert "None" not in text, text
    assert "1. Engineer" in text


def test_empty_resume_renders_empty_text() -> None:
    assert convert_json_resume_to_text(JSONResume.model_validate({"basics": {"name": "X Y"}})).startswith(
        "=== BASIC INFORMATION ==="
    )


# ------------------------------------------------------ employer-only depth ---
def _employer_text(employer: str, prose: str) -> str:
    payload = {
        "basics": {"name": "A B"},
        "work": [{"name": employer, "position": "Engineer", "summary": prose}],
    }
    return _redactor_for(JSONResume.model_validate(payload))(prose)


def test_short_acronym_employer_is_masked_in_prose() -> None:
    """2-3 char employer names are all-caps/digit brands, and must not leak."""
    for employer, prose in (
        ("IBM", "Built ETL for IBM"),
        ("TCS", "Onsite at TCS"),
        ("2U", "Contract at 2U"),
    ):
        out = _employer_text(employer, prose)
        assert employer not in out, f"{employer} leaked: {out!r}"
        assert "Client 1" in out


def test_lowercase_short_employer_is_left_alone() -> None:
    """The precision side of the acronym rule: real English words are not brands."""
    assert _employer_text("Air", "Worked at Air") == "Worked at Air"
    assert _entity_aliases("Air", include_head=True, deep=True) == []


def test_employer_head_pair_uses_combined_length() -> None:
    """A 4-char first token still yields a two-token head for employers."""
    assert _entity_aliases("Tata Consultancy Services", include_head=True, deep=True) == [
        "Tata Consultancy Services",
        "Tata Consultancy",
    ]
    out = _employer_text("Tata Consultancy Services", "Joined Tata Consultancy in 2024")
    assert "Tata" not in out
    assert "Client 1" in out


def test_longer_name_wins_over_an_overlapping_short_alias() -> None:
    """Employer "Sree Venkateswara Systems" and school "Sree Venkateswara College
    Of Engeneering" share a head; the long name must be masked whole, not
    half-masked into "Client 1 College Of Engeneering"."""
    payload = {
        "basics": {"name": "A B"},
        "work": [{"name": "Sree Venkateswara Systems", "position": "Engineer"}],
        "education": [
            {
                "institution": "Sree Venkateswara College Of Engeneering",
                "area": "Computer Science",
                "studyType": "B.Tech",
            }
        ],
    }
    redact = _redactor_for(JSONResume.model_validate(payload))
    out = redact("Graduated from Sree Venkateswara College Of Engeneering.")
    assert out == "Graduated from Institution 2."
    assert redact("Shipped at Sree Venkateswara Systems.") == "Shipped at Client 1."


def test_school_aliases_stay_exact_match_only() -> None:
    """Scope decision: deep surface forms are generated for employers only, so a
    school name is masked on an exact full-name hit and nothing else."""
    institution = "Sree Venkateswara College Of Engeneering"
    assert _entity_aliases(institution, include_head=True, deep=False) == [institution]
    assert _entity_aliases("MIT", include_head=True, deep=False) == []
