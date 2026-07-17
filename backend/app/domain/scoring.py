"""Weighted candidate scoring.

Score = title 30% + skills 30% + experience 20% + location 10% + education 10%.
The weights are a **named, versioned profile** (`SCORE_VERSION`); every stored
result records the version so historical scores stay reproducible and comparable.
"""

from __future__ import annotations

import re

from app.domain import experience as experience_mod
from app.domain import skills as skills_mod
from app.domain.models import (
    RawProfile,
    ScoreBreakdown,
    ScoredCandidate,
    SearchCriteria,
)

SCORE_VERSION = "v1"

WEIGHTS = {
    "title": 0.30,
    "skills": 0.30,
    "experience": 0.20,
    "location": 0.10,
    "education": 0.10,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Words that carry seniority/format, not the core role — ignored for title overlap.
_TITLE_STOPWORDS = {"the", "a", "an", "of", "and", "for", "with", "at", "in"}


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _TITLE_STOPWORDS}


def title_score(required_title: str, candidate_title: str | None,
                headline: str | None) -> float:
    """Token-overlap of the required title against the candidate's title/headline."""
    required = _tokens(required_title)
    if not required:
        return 0.0
    candidate = _tokens(candidate_title) | _tokens(headline)
    overlap = len(required & candidate)
    return overlap / len(required)


def experience_score(total_years: float, min_experience: float) -> float:
    if min_experience <= 0:
        return 1.0
    return min(1.0, total_years / min_experience)


def location_score(required: str | None, candidate: str | None) -> float:
    if not required:
        return 1.0  # no requirement → neutral full credit
    cand_tokens = _tokens(candidate)
    if "remote" in _tokens(required) and "remote" in cand_tokens:
        return 1.0
    req_tokens = _tokens(required)
    return 1.0 if req_tokens & cand_tokens else 0.0


def education_score(profile: RawProfile) -> float:
    has_education = bool(profile.education)
    has_credentials = bool(profile.certifications or profile.licenses)
    return 0.5 * has_education + 0.5 * has_credentials


def _reasons(
    *,
    title: float,
    skill_match: skills_mod.SkillMatch,
    total_years: float,
    criteria: SearchCriteria,
    location: float,
) -> list[str]:
    reasons: list[str] = []
    if title >= 0.7:
        reasons.append("Job title strongly matches")
    elif title >= 0.4:
        reasons.append("Job title partially matches")

    if criteria.min_experience > 0 and total_years >= criteria.min_experience:
        reasons.append(
            f"{total_years:g} years experience (meets {criteria.min_experience:g} required)"
        )
    elif total_years > 0:
        reasons.append(f"{total_years:g} years experience")

    if skill_match.matched:
        shown = ", ".join(skill_match.matched[:5])
        reasons.append(f"Has {shown}")

    if criteria.location and location >= 1.0:
        reasons.append("Location matches")

    return reasons


def score_candidate(
    profile: RawProfile,
    criteria: SearchCriteria,
    *,
    total_years: float | None = None,
) -> ScoredCandidate:
    """Score a single candidate against the recruiter's criteria (deterministic v1)."""
    if total_years is None:
        total_years = experience_mod.compute_total_experience_years(profile.experience)

    skill_match = skills_mod.match_skills(criteria.skills, profile.skills)

    s_title = title_score(criteria.job_title, profile.current_title, profile.headline)
    s_skills = skill_match.ratio
    s_experience = experience_score(total_years, criteria.min_experience)
    s_location = location_score(criteria.location, profile.location)
    s_education = education_score(profile)

    total = (
        WEIGHTS["title"] * s_title
        + WEIGHTS["skills"] * s_skills
        + WEIGHTS["experience"] * s_experience
        + WEIGHTS["location"] * s_location
        + WEIGHTS["education"] * s_education
    )

    breakdown = ScoreBreakdown(
        title=round(s_title * 100, 1),
        skills=round(s_skills * 100, 1),
        experience=round(s_experience * 100, 1),
        location=round(s_location * 100, 1),
        education=round(s_education * 100, 1),
    )

    return ScoredCandidate(
        match_score=round(total * 100, 1),
        score_version=SCORE_VERSION,
        breakdown=breakdown,
        matched_skills=skill_match.matched,
        missing_skills=skill_match.missing,
        reasons=_reasons(
            title=s_title,
            skill_match=skill_match,
            total_years=total_years,
            criteria=criteria,
            location=s_location,
        ),
        total_experience_years=total_years,
    )
