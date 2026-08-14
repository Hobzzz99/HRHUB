"""Selecting employers must mean only those employers come back.

LinkedIn's own filter should already have restricted the result set, but it runs
server-side and can silently fail to apply — a changed panel, a missed click. The
promise is therefore kept again where the employer is actually known, so a gap in
the automation can never turn into a wrong candidate on the shortlist.
"""

from __future__ import annotations

import pytest

from app.domain.filtering import apply_filters
from app.domain.models import ExperienceItem, RawProfile, SearchCriteria
from app.domain.scoring import score_candidate
from app.providers.search_plan import plan, relax

BIG_FOUR = ["Deloitte", "PwC", "EY", "KPMG"]


def _profile(company: str | None, **over) -> RawProfile:
    base = dict(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name="X",
        headline="External Audit Manager",
        current_title="External Audit Manager",
        current_company=company,
        location="Cairo, Egypt",
        experience=[ExperienceItem(title="External Audit Manager", company=company)],
    )
    base.update(over)
    return RawProfile(**base)


def _decide(profile: RawProfile, companies: list[str]):
    criteria = SearchCriteria(job_title="external audit manager", companies=companies)
    return apply_filters(profile, score_candidate(profile, criteria, total_years=8.0), criteria)


@pytest.mark.parametrize(
    "employer", ["Deloitte", "Deloitte & Touche", "Ernst & Young LLP", "KPMG Middle East", "PwC"]
)
def test_big_four_employees_are_kept(employer):
    assert _decide(_profile(employer), BIG_FOUR).keep


@pytest.mark.parametrize("employer", ["Grant Thornton", "AMSG Chartered Accountants", "BDO"])
def test_everyone_else_is_discarded(employer):
    decision = _decide(_profile(employer), BIG_FOUR)
    assert not decision.keep
    assert any("not" in r for r in decision.reasons)


def test_an_unreadable_employer_is_discarded_not_assumed():
    """The hole this closes: a card with no employer passed the cheap pre-filter,
    and nothing checked again once the profile was open."""
    profile = _profile(None, experience=[])
    decision = _decide(profile, BIG_FOUR)
    assert not decision.keep


def test_the_most_recent_role_stands_in_for_a_missing_current_employer():
    profile = _profile(None, experience=[ExperienceItem(title="Audit Manager", company="KPMG")])
    assert _decide(profile, BIG_FOUR).keep


def test_no_employer_requested_keeps_everyone():
    assert _decide(_profile("Grant Thornton"), []).keep


def test_the_employer_filter_is_never_traded_away_when_widening():
    """Someone who asked for the Big Four does not want a longer list from elsewhere."""
    criteria = SearchCriteria(
        job_title="audit manager", companies=BIG_FOUR, location="Egypt", enforce_location=True
    )
    steps = plan(criteria)
    steps, first = relax(steps)      # location goes
    steps, second = relax(steps)     # nothing else may
    assert first.label == "location"
    assert second is None
    assert [s.label for s in steps] == ["employer"]
