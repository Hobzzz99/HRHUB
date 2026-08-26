"""Domain data structures shared by providers and scoring.

These are deliberately provider-neutral. A `SearchHit` is the cheap card data a
provider returns from a search; a `RawProfile` is the full extracted profile.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExperienceItem(BaseModel):
    title: str | None = None
    company: str | None = None
    # Dates are free-form strings ("2020", "Jan 2020", "2020-03", ISO) so any
    # provider can supply what it has; experience.py parses them robustly.
    start: str | None = None
    end: str | None = None  # None / "present" / "current" => ongoing
    location: str | None = None
    description: str | None = None


class EducationItem(BaseModel):
    school: str | None = None
    degree: str | None = None
    field: str | None = None
    start: str | None = None
    end: str | None = None


class SearchHit(BaseModel):
    """Cheap, list-page data used for the conservative pre-filter."""

    source_profile_url: str
    name: str | None = None
    headline: str | None = None
    current_company: str | None = None
    location: str | None = None


class RawProfile(BaseModel):
    """Full profile as extracted by a provider (pre-scoring)."""

    source: str
    source_profile_url: str
    source_id: str | None = None
    name: str
    headline: str | None = None
    current_title: str | None = None
    current_company: str | None = None
    location: str | None = None
    about: str | None = None
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    licenses: list[dict] = Field(default_factory=list)
    certifications: list[dict] = Field(default_factory=list)
    languages: list[str] = Field(default_factory=list)
    profile_picture_url: str | None = None
    raw: dict | None = None


class SearchCriteria(BaseModel):
    """Recruiter requirements — used for searching, scoring, and filtering."""

    job_title: str
    critical_skills: list[str] = Field(default_factory=list)
    location: str | None = None
    min_experience: float = 0.0
    #: Career-stage window, expressed the way it appears on a profile. Tested
    #: against the candidate's *earliest* graduation — see domain/education.py.
    #: Discard anyone whose career shows no evidence of the job title's
    #: subject. Default on: a search for "external audit manager" returning a
    #: finance manager is not a near miss, it is a wrong answer.
    require_title_match: bool = True
    graduation_year_from: int | None = None
    graduation_year_to: int | None = None
    keywords: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    #: LinkedIn company ids, taken straight from a search URL the recruiter
    #: pasted. Exact, because LinkedIn resolved them — used in preference to
    #: driving the filter panel for `companies`.
    company_ids: list[str] = Field(default_factory=list)
    #: LinkedIn geo ids, taken from a pasted search URL the same way company ids
    #: are. Exact, because LinkedIn resolved them — "Saudi Arabia" as free text
    #: is ambiguous, and its own id is not.
    location_ids: list[str] = Field(default_factory=list)
    industry: str | None = None
    max_results: int = 25
    min_match_score: float = 0.0
    enforce_location: bool = False


class SkillMatch(BaseModel):
    matched: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    ratio: float = 1.0  # matched / required (1.0 when nothing required)


class ScoreBreakdown(BaseModel):
    """Sub-scores as percentages (0-100)."""

    title: float = 0.0
    keywords: float = 0.0
    experience: float = 0.0
    location: float = 0.0


class ScoredCandidate(BaseModel):
    match_score: float  # 0-100
    score_version: str
    breakdown: ScoreBreakdown
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    total_experience_years: float = 0.0


class FilterDecision(BaseModel):
    keep: bool
    reasons: list[str] = Field(default_factory=list)  # why discarded (if not kept)
