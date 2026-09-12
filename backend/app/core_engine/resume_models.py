"""JSONResume models (copied from vendor models.py:20-207, I9 unchanged).

Pydantic models for the JSONResume format and per-section typed schemas.
Imports rewritten to no vendor dependencies.
"""

from __future__ import annotations

from pydantic import BaseModel


class Location(BaseModel):
    """Location information for JSON Resume format."""

    address: str | None = None
    postalCode: str | None = None
    city: str | None = None
    countryCode: str | None = None
    region: str | None = None


class Profile(BaseModel):
    """Social profile information for JSON Resume format."""

    network: str | None = None
    username: str | None = None
    url: str


class Basics(BaseModel):
    """Basic information for JSON Resume format."""

    name: str
    email: str | None = None
    phone: str | None = None
    url: str | None = None
    summary: str | None = None
    location: Location | None = None
    profiles: list[Profile] | None = None


class Work(BaseModel):
    """Work experience for JSON Resume format."""

    name: str | None = None
    position: str | None = None
    url: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    summary: str | None = None
    highlights: list[str] | None = None


class Volunteer(BaseModel):
    """Volunteer experience for JSON Resume format."""

    organization: str | None = None
    position: str | None = None
    url: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    summary: str | None = None
    highlights: list[str] | None = None


class Education(BaseModel):
    """Education information for JSON Resume format."""

    institution: str | None = None
    url: str | None = None
    area: str | None = None
    studyType: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    score: str | None = None
    courses: list[str] | None = None


class Award(BaseModel):
    """Award information for JSON Resume format."""

    title: str | None = None
    date: str | None = None
    awarder: str | None = None
    summary: str | None = None


class Certificate(BaseModel):
    """Certificate information for JSON Resume format."""

    name: str | None = None
    date: str | None = None
    issuer: str | None = None
    url: str | None = None


class Publication(BaseModel):
    """Publication information for JSON Resume format."""

    name: str | None = None
    publisher: str | None = None
    releaseDate: str | None = None
    url: str | None = None
    summary: str | None = None


class Skill(BaseModel):
    """Skill information for JSON Resume format."""

    name: str | None = None
    level: str | None = None
    keywords: list[str] | None = None


class Language(BaseModel):
    """Language information for JSON Resume format."""

    language: str | None = None
    fluency: str | None = None


class Interest(BaseModel):
    """Interest information for JSON Resume format."""

    name: str | None = None
    keywords: list[str] | None = None


class Reference(BaseModel):
    """Reference information for JSON Resume format."""

    name: str | None = None
    reference: str | None = None


class Project(BaseModel):
    """Project information for JSON Resume format."""

    name: str | None = None
    startDate: str | None = None
    endDate: str | None = None
    description: str | None = None
    highlights: list[str] | None = None
    url: str | None = None
    technologies: list[str] | None = None
    skills: list[str] | None = None


class BasicsSection(BaseModel):
    """Basics section containing basic information."""

    basics: Basics | None = None


class WorkSection(BaseModel):
    """Work section containing a list of work experiences."""

    work: list[Work] | None = None


class EducationSection(BaseModel):
    """Education section containing a list of education entries."""

    education: list[Education] | None = None


class SkillsSection(BaseModel):
    """Skills section containing a list of skill categories."""

    skills: list[Skill] | None = None


class ProjectsSection(BaseModel):
    """Projects section containing a list of projects."""

    projects: list[Project] | None = None


class AwardsSection(BaseModel):
    """Awards section containing a list of awards."""

    awards: list[Award] | None = None


class JSONResume(BaseModel):
    """Complete JSON Resume format model."""

    basics: Basics | None = None
    work: list[Work] | None = None
    volunteer: list[Volunteer] | None = None
    education: list[Education] | None = None
    awards: list[Award] | None = None
    certificates: list[Certificate] | None = None
    publications: list[Publication] | None = None
    skills: list[Skill] | None = None
    languages: list[Language] | None = None
    interests: list[Interest] | None = None
    references: list[Reference] | None = None
    projects: list[Project] | None = None
