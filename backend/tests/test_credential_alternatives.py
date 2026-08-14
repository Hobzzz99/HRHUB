"""One requirement, several acceptable qualifications.

The same qualification has different names by country. Requiring "CPA" — the
American one — in Egypt rejected Audit Managers at EY and KPMG who hold ACCA or
ESAA. Across the real archive CPA alone matches 42 people; CPA, ACCA or ESAA
matches 60.

Critical skills are and-ed, which is right for skills and wrong for credentials:
nobody holds all three. So one requirement may list alternatives.
"""

from __future__ import annotations

import pytest

from app.domain import filtering
from app.domain.models import ExperienceItem, RawProfile, SearchCriteria
from app.domain.scoring import score_candidate


def _profile(name: str, **over) -> RawProfile:
    base = dict(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name=name,
        headline="Audit Manager",
        current_title="Audit Manager",
        current_company="EY",
        experience=[ExperienceItem(title="External Audit Manager", company="EY")],
    )
    base.update(over)
    return RawProfile(**base)


def _kept(profile: RawProfile, critical: list[str]) -> bool:
    criteria = SearchCriteria(
        job_title="external audit manager", critical_skills=critical, min_match_score=0
    )
    return filtering.apply_filters(profile, score_candidate(profile, criteria), criteria).keep


@pytest.mark.parametrize("written", ["CPA / ACCA / ESAA", "CPA|ACCA|ESAA", "CPA or ACCA or ESAA"])
def test_any_listed_qualification_satisfies_the_requirement(written):
    assert _kept(_profile("Mohamed Fathy Bakr, ACCA, FESAA"), [written])
    assert _kept(_profile("Ayman Mohamed, ESAA"), [written])
    assert _kept(_profile("Ahmed Osman, CPA"), [written])


def test_holding_none_of_them_is_still_rejected():
    """Alternatives widen the requirement; they must not remove it."""
    assert not _kept(_profile("Ahmed Sedeik"), ["CPA / ACCA / ESAA"])


def test_a_single_requirement_is_unchanged():
    assert _kept(_profile("Ahmed Osman, CPA"), ["CPA"])
    assert not _kept(_profile("Mohamed Fathy Bakr, ACCA"), ["CPA"])


def test_separate_requirements_are_still_all_required():
    """Two entries mean both; alternatives live inside one entry."""
    profile = _profile("Ayman Mohamed, ESAA")
    assert not _kept(profile, ["CPA / ACCA", "CIA"])


class TestSplitting:
    def test_plain_term_is_left_alone(self):
        assert filtering.alternatives("CPA") == ["CPA"]

    def test_whitespace_is_trimmed(self):
        assert filtering.alternatives(" CPA /  ACCA ") == ["CPA", "ACCA"]

    def test_a_term_that_is_only_a_separator_survives(self):
        """Never return an empty list — that would silently drop the filter."""
        assert filtering.alternatives("/") == ["/"]

    def test_or_inside_a_word_is_not_a_separator(self):
        assert filtering.alternatives("Corporate Reporting") == ["Corporate Reporting"]
