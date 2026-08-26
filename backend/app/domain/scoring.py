"""Weighted candidate scoring.

Score = title 30% + keywords 30% + experience 30% + location 10%.
The weights are a **named, versioned profile** (`SCORE_VERSION`); every stored
result records the version so historical scores stay reproducible and comparable.

``v2`` replaced ``v1``'s skills-list matching with keyword matching against the
candidate's headline and job titles, raised experience from 20% to 30%, and
dropped the education component entirely.

``v3`` rewrote the title component (`domain/job_titles.py`). v2 compared the
required title to the candidate's as a bag of words, so **Finance Manager**
scored 33% against *external audit manager* on the shared word "manager" — a
seniority word every management title contains. v3 separates what the job *is*
from how senior it is, judges the job across the candidate's whole career rather
than their current line, and treats the subject as a gate rather than a weight.
"""

from __future__ import annotations

import re

from app.domain import experience as experience_mod
from app.domain import job_titles as job_titles_mod
from app.domain import keywords as keywords_mod
from app.domain import nationality as nationality_mod
from app.domain.models import (
    RawProfile,
    ScoreBreakdown,
    ScoredCandidate,
    SearchCriteria,
)

SCORE_VERSION = "v4"

WEIGHTS = {
    "title": 0.30,
    "keywords": 0.30,
    "experience": 0.30,
    "location": 0.10,
}

_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Words that carry seniority/format, not the core role — ignored for title overlap.
_TITLE_STOPWORDS = {"the", "a", "an", "of", "and", "for", "with", "at", "in"}


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in _TOKEN_RE.findall(text.lower()) if t not in _TITLE_STOPWORDS}


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


def _reasons(
    *,
    title: float,
    keyword_match: keywords_mod.KeywordMatch,
    total_years: float,
    relevant_years: float,
    criteria: SearchCriteria,
    location: float,
) -> list[str]:
    reasons: list[str] = []
    if title >= 0.7:
        reasons.append("Job title strongly matches")
    elif title >= 0.4:
        reasons.append("Job title partially matches")

    if criteria.min_experience > 0 and relevant_years >= criteria.min_experience:
        field = " in this field" if relevant_years != total_years else ""
        reasons.append(
            f"{relevant_years:g} years experience{field} "
            f"(meets {criteria.min_experience:g} required)"
        )
    elif total_years > 0:
        reasons.append(f"{total_years:g} years experience")

    if keyword_match.matched:
        shown = ", ".join(keyword_match.matched[:5])
        reasons.append(f"Title mentions {shown}")

    if criteria.location and location >= 1.0:
        reasons.append("Location matches")

    return reasons


def _stated_components(criteria: SearchCriteria) -> set[str]:
    """Which components the recruiter actually asked for.

    Job title is always stated — the form requires it. The rest are optional,
    and leaving one blank means "I don't care", which is different from "every
    candidate passes".
    """
    stated = {"title"}
    if criteria.keywords:
        stated.add("keywords")
    if criteria.min_experience > 0:
        stated.add("experience")
    if criteria.location:
        stated.add("location")
    return stated


def _weighted_total(scores: dict[str, float], *, stated: set[str]) -> float:
    """Weighted average across the stated components only.

    An unstated component is **dropped and its weight redistributed**, rather
    than scored 1.0. Both approaches avoid penalising anyone for a criterion
    nobody set, but awarding full marks hands every candidate the same free
    points — which flattens the ranking and, worse, makes a score threshold mean
    different things depending on which boxes were filled in. Redistributing
    keeps 100 meaning "matched everything you asked for" in every case.
    """
    active = sum(WEIGHTS[name] for name in stated)
    if active <= 0:  # defensive: title is always stated, so unreachable today
        return 0.0
    return sum(WEIGHTS[name] * scores[name] for name in stated) / active


def _nationality_evidence(profile: RawProfile, criteria: SearchCriteria) -> list[str]:
    """Why we think this person holds the nationality asked for.

    Shown first, because it is the one judgement here the system cannot actually
    make — LinkedIn has no nationality field — and a recruiter needs to see the
    reasoning rather than a silent pass.
    """
    if not criteria.nationality:
        return []
    signal = nationality_mod.assess(profile, criteria.nationality)
    if signal.unknown:
        # Said plainly, because this candidate has *not* been checked and the
        # recruiter would otherwise assume a filtered list means a verified one.
        return [f"{criteria.nationality} nationality unverified — no education listed"]
    return signal.evidence


def score_candidate(
    profile: RawProfile,
    criteria: SearchCriteria,
    *,
    total_years: float | None = None,
) -> ScoredCandidate:
    """Score a single candidate against the recruiter's criteria (deterministic v3)."""
    if total_years is None:
        total_years = experience_mod.compute_total_experience_years(profile.experience)

    # What the experience bar is measured against. Counting a whole career let a
    # finance director who audited briefly a decade ago clear a ten-year audit
    # requirement, while an audit manager with eight solid years did not.
    years_for_bar = total_years
    if (
        criteria.experience_in_field
        and criteria.min_experience > 0
        # Only when the dates can actually be read. A profile whose roles carry
        # no parseable dates would otherwise measure zero years in the field and
        # be rejected for it — punishing someone for how LinkedIn rendered their
        # page rather than for their career.
        and experience_mod.has_dated_roles(profile.experience)
    ):
        years_for_bar = experience_mod.compute_relevant_experience_years(
            profile.experience,
            lambda item: job_titles_mod.role_is_in_field(
                criteria.job_title, criteria.keywords, item
            ),
        )

    keyword_match = keywords_mod.match_keywords_in_profile(criteria.keywords, profile)

    s_title = job_titles_mod.title_score(criteria.job_title, profile)
    s_keywords = keyword_match.ratio
    s_experience = experience_score(years_for_bar, criteria.min_experience)
    s_location = location_score(criteria.location, profile.location)

    total = _weighted_total(
        {
            "title": s_title,
            "keywords": s_keywords,
            "experience": s_experience,
            "location": s_location,
        },
        stated=_stated_components(criteria),
    )

    breakdown = ScoreBreakdown(
        title=round(s_title * 100, 1),
        keywords=round(s_keywords * 100, 1),
        experience=round(s_experience * 100, 1),
        location=round(s_location * 100, 1),
    )

    return ScoredCandidate(
        match_score=round(total * 100, 1),
        score_version=SCORE_VERSION,
        breakdown=breakdown,
        matched_keywords=keyword_match.matched,
        missing_keywords=keyword_match.missing,
        reasons=_nationality_evidence(profile, criteria) + _reasons(
            title=s_title,
            keyword_match=keyword_match,
            total_years=total_years,
            relevant_years=years_for_bar,
            criteria=criteria,
            location=s_location,
        ),
        total_experience_years=total_years,
        relevant_experience_years=years_for_bar,
    )
