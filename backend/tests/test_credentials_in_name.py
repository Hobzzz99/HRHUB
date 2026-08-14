"""Finance and audit people write their credential into their name.

"Walid Gad, CPA, CMA" is how this market presents itself, and LinkedIn shows the
name more prominently than the headline. Judging a credential requirement
without reading it discarded 11 of 42 CPAs in the real profile archive — every
one an audit manager who happened to write it there rather than in a skills
list nobody maintains.
"""

from __future__ import annotations

from app.domain import filtering, keywords
from app.domain.models import ExperienceItem, RawProfile, SearchCriteria
from app.domain.scoring import score_candidate


def _profile(name: str, **over) -> RawProfile:
    base = dict(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name=name,
        headline="Audit Manager",
        current_title="Audit Manager",
        current_company="PwC Middle East",
        experience=[ExperienceItem(title="Audit Manager", company="PwC Middle East")],
    )
    base.update(over)
    return RawProfile(**base)


def _kept(profile: RawProfile, critical: list[str]) -> bool:
    criteria = SearchCriteria(job_title="external audit manager", critical_skills=critical)
    return filtering.apply_filters(profile, score_candidate(profile, criteria), criteria).keep


class TestCredentialInTheName:
    def test_cpa_in_the_name_satisfies_a_critical_skill(self):
        assert _kept(_profile("Abdelrahman Tawfik, CPA"), ["CPA"])

    def test_someone_without_it_is_still_rejected(self):
        """The filter must stay a filter."""
        assert not _kept(_profile("Abdelrahman Tawfik"), ["CPA"])

    def test_several_credentials_in_one_name(self):
        profile = _profile("Walid Gad, CPA ,CMA")
        assert _kept(profile, ["CPA"])
        assert _kept(profile, ["CMA"])

    def test_the_name_is_a_searchable_field(self):
        fields = keywords.searchable_fields(_profile("Mohamed Hegazy CPA, IFRS"))
        assert "Mohamed Hegazy CPA, IFRS" in fields

    def test_a_credential_elsewhere_still_works(self):
        """Adding the name must not have replaced the fields that already worked."""
        profile = _profile("Ahmed Sedeik", skills=["CPA", "IFRS"])
        assert _kept(profile, ["CPA"])

    def test_a_name_does_not_donate_words_across_fields(self):
        """Each field is matched whole, so a name cannot complete a phrase.

        "Audit" from the title plus "External" from a name must not together
        satisfy "external audit" — that cross-field bleed is the bug the
        per-field design exists to prevent.
        """
        profile = _profile("External Gad", current_title="Internal Audit Manager")
        match = keywords.match_keywords_in_profile(["external audit"], profile)
        assert match.matched == []
