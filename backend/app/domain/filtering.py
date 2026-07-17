"""Post-scoring filter rules.

Discard a scored candidate when it fails any hard requirement. Duplicate profiles
are handled separately at the persistence layer (unique `(source, url)`).
"""

from __future__ import annotations

from app.domain import skills as skills_mod
from app.domain.models import FilterDecision, RawProfile, ScoredCandidate, SearchCriteria


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
    if criteria.critical_skills:
        critical = skills_mod.match_skills(criteria.critical_skills, profile.skills)
        if critical.missing:
            reasons.append("Missing critical skills: " + ", ".join(critical.missing))

    # Score below threshold.
    if scored.match_score < criteria.min_match_score:
        reasons.append(
            f"Score {scored.match_score:g} below threshold {criteria.min_match_score:g}"
        )

    # Optional hard location filter.
    if criteria.enforce_location and criteria.location and scored.breakdown.location <= 0:
        reasons.append(f"Location does not match '{criteria.location}'")

    return FilterDecision(keep=not reasons, reasons=reasons)
