"""Post-scoring filter rules.

Discard a scored candidate when it fails any hard requirement. Duplicate profiles
are handled separately at the persistence layer (unique `(source, url)`).
"""

from __future__ import annotations

import re

from app.domain import companies as companies_mod
from app.domain import education as education_mod
from app.domain import job_titles as job_titles_mod
from app.domain import keywords as keywords_mod
from app.domain import skills as skills_mod
from app.domain.models import FilterDecision, RawProfile, ScoredCandidate, SearchCriteria

#: Separators that turn one requirement into a list of acceptable alternatives.
_ALTERNATIVES_RE = re.compile(r"\s*[/|]\s*|\s+or\s+", re.IGNORECASE)


def alternatives(term: str) -> list[str]:
    """Split a requirement into the forms that would each satisfy it.

    Written for credentials, where the same qualification has different names by
    country. Requiring "CPA" in Egypt rejects Audit Managers at EY and KPMG for
    holding ACCA or ESAA instead — the locally correct qualification. Across the
    real profile archive, CPA alone matches 42 people; CPA, ACCA or ESAA matches
    60.

    Critical skills are otherwise **and**-ed together, which is right for skills
    but wrong for credentials: nobody holds all three. So a recruiter writes
    "CPA / ACCA / ESAA" as one requirement and any of them satisfies it.
    """
    parts = [part.strip() for part in _ALTERNATIVES_RE.split(term)]
    return [part for part in parts if part] or [term.strip()]


def _has_critical_skill(term: str, profile: RawProfile) -> bool:
    """A critical skill counts as present if the profile evidences it anywhere.

    Checked against the listed skills **and** the headline/job titles/name,
    because LinkedIn's Skills section is frequently incomplete — someone whose
    title is "Vendor Manager" plainly has vendor management whether or not they
    added it to a list. This is a hard filter, so it must only reject when
    confident.
    """
    for option in alternatives(term):
        if skills_mod.match_skills([option], profile.skills).matched:
            return True
        if keywords_mod.match_keywords_in_profile([option], profile).matched:
            return True
    return False


def apply_filters(
    profile: RawProfile,
    scored: ScoredCandidate,
    criteria: SearchCriteria,
) -> FilterDecision:
    reasons: list[str] = []

    # Years of experience below the minimum required.
    if criteria.min_experience > 0 and scored.total_experience_years < criteria.min_experience:
        reasons.append(
            f"Only {scored.total_experience_years:g} yrs experience "
            f"(< {criteria.min_experience:g} required)"
        )

    # Any critical skill missing.
    missing_critical = [
        term
        for term in criteria.critical_skills
        if term and term.strip() and not _has_critical_skill(term, profile)
    ]
    if missing_critical:
        reasons.append("Missing critical skills: " + ", ".join(missing_critical))

    # Employer. LinkedIn's own filter should already have restricted the result
    # set, but that runs server-side and can silently not apply — so the promise
    # is kept here, where the employer is actually known. "Only show me people
    # at the Big Four" has to mean exactly that, including for a profile whose
    # employer we could not read.
    if criteria.companies:
        employer = companies_mod.current_employer(profile)
        if not companies_mod.matches(criteria.companies, employer, allow_unknown=False):
            reasons.append(
                f"Works at {employer or 'an employer we could not read'}, "
                "not " + " / ".join(criteria.companies)
            )

    # The job itself. A candidate with no trace of the role's subject anywhere
    # in their career is not a weak match, they are the wrong person — and
    # letting them through on experience and location alone is what returned a
    # finance manager for an external audit search.
    if criteria.require_title_match:
        absent = job_titles_mod.missing_domain_words(criteria.job_title, profile)
        if absent:
            reasons.append(
                "No experience in: " + ", ".join(absent)
            )

    # Career stage, read from the earliest graduation year on the profile.
    in_window, why = education_mod.in_range(
        profile.education,
        year_from=criteria.graduation_year_from,
        year_to=criteria.graduation_year_to,
    )
    if not in_window and why:
        reasons.append(why)

    # Score below threshold.
    if scored.match_score < criteria.min_match_score:
        reasons.append(
            f"Score {scored.match_score:g} below threshold {criteria.min_match_score:g}"
        )

    # Optional hard location filter.
    if criteria.enforce_location and criteria.location and scored.breakdown.location <= 0:
        reasons.append(f"Location does not match '{criteria.location}'")

    return FilterDecision(keep=not reasons, reasons=reasons)
