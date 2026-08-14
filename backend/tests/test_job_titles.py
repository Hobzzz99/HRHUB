"""What a job title is allowed to prove, and how strongly.

Two failures found by re-scoring the real profile archive against a search for
*external audit manager*, both fixed in v4:

* A self-declared LinkedIn skill tag reading "External Audit" let finance
  managers with no audit role in their history clear the domain gate.
* An internal auditor with one external role from early in their career scored
  100 — joint top — because every internal role was credited in full for the
  shared word "audit".
"""

from __future__ import annotations

from app.domain import job_titles
from app.domain.models import ExperienceItem, RawProfile

REQUIRED = "external audit manager"


def _profile(current: str, past: list[str], *, skills: list[str] | None = None) -> RawProfile:
    return RawProfile(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name="X",
        headline=current,
        current_title=current,
        experience=[ExperienceItem(title=title, company="Acme") for title in past],
        skills=skills or [],
    )


class TestSkillsDoNotProveTheProfession:
    def test_skill_tag_alone_does_not_satisfy_the_domain(self):
        finance = _profile(
            "Finance Manager",
            ["Finance Manager", "Group Finance Manager"],
            skills=["External Audit", "IFRS"],
        )
        assert job_titles.missing_domain_words(REQUIRED, finance) == ["audit", "external"]
        assert job_titles.title_score(REQUIRED, finance) == 0.0

    def test_skill_tag_cannot_supply_the_word_a_career_lacks(self):
        """The real case: an internal auditor tagged with "External Audit".

        Every domain word but one is genuinely evidenced, so this is where a
        self-declared tag used to make the difference between in and out.
        """
        internal = _profile(
            "Internal Audit Manager",
            ["Internal Audit Manager", "Senior Internal Auditor"],
            skills=["External Audit", "Internal Audit"],
        )
        assert job_titles.missing_domain_words(REQUIRED, internal) == ["external"]

        # An unevidenced domain word is what the hard filter acts on.
        from app.domain.filtering import apply_filters
        from app.domain.models import SearchCriteria
        from app.domain.scoring import score_candidate

        criteria = SearchCriteria(job_title=REQUIRED)
        decision = apply_filters(internal, score_candidate(internal, criteria), criteria)
        assert not decision.keep

    def test_a_job_title_still_proves_it(self):
        auditor = _profile("Audit Manager", ["Audit Manager", "External Auditor"])
        assert job_titles.missing_domain_words(REQUIRED, auditor) == []
        assert job_titles.title_score(REQUIRED, auditor) > 0

    def test_an_employer_still_proves_it(self):
        profile = RawProfile(
            source="linkedin",
            source_profile_url="https://example.com/in/y",
            name="Y",
            headline="Manager",
            current_title="Manager",
            experience=[ExperienceItem(title="Manager", company="External Audit Partners")],
        )
        assert "external" not in job_titles.missing_domain_words(REQUIRED, profile)

    def test_skills_remain_available_to_keyword_matching(self):
        """The gate ignores skills; keyword scoring must not."""
        from app.domain import keywords

        profile = _profile("Finance Manager", ["Finance Manager"], skills=["External Audit"])
        assert keywords.match_keywords_in_profile(["external audit"], profile).ratio == 1.0


class TestDepthWeighsTheDistinguishingWord:
    def test_internal_auditor_ranks_below_an_external_one(self):
        internal = _profile(
            "Internal Audit Manager",
            [
                "Internal Audit Manager",
                "Internal Audit Assistant Manager",
                "Internal Audit Supervisor",
                "Senior Internal Auditor",
                "Internal Auditor",
                "External Auditor",  # one role of six
            ],
        )
        external = _profile(
            "External Audit Manager",
            ["External Audit Manager", "Senior External Auditor", "External Auditor"],
        )
        assert job_titles.title_score(REQUIRED, internal) < job_titles.title_score(
            REQUIRED, external
        )

    def test_a_career_in_the_domain_still_scores_full_depth(self):
        profile = _profile(
            "External Audit Manager", ["External Audit Manager", "Senior External Auditor"]
        )
        assert job_titles.domain_depth(REQUIRED, profile) == 1.0

    def test_a_role_matching_half_the_domain_counts_half(self):
        profile = _profile("Audit Manager", ["Internal Audit Manager", "External Audit Manager"])
        # The internal role evidences audit but contradicts external; the other has both.
        assert job_titles.domain_depth(REQUIRED, profile) == 0.75

    def test_the_shared_word_alone_no_longer_earns_full_depth(self):
        internal = _profile("Internal Audit Manager", ["Internal Auditor", "External Auditor"])
        assert job_titles.domain_depth(REQUIRED, internal) == 0.75

    def test_a_title_of_one_domain_word_is_unaffected(self):
        profile = _profile("Auditor", ["Auditor", "Accountant"])
        assert job_titles.domain_depth("audit manager", profile) == 0.5


class TestTheUnnamedDefault:
    """At an audit firm the statutory work is just called "Audit"."""

    def test_an_unqualified_audit_manager_is_an_external_auditor(self):
        big_four = RawProfile(
            source="linkedin",
            source_profile_url="https://example.com/in/z",
            name="Z",
            headline="Audit Manager",
            current_title="Audit Manager",
            current_company="PwC Middle East",
            experience=[
                ExperienceItem(title="Audit Manager", company="PwC Middle East"),
                ExperienceItem(title="Senior Auditor", company="PwC Middle East"),
            ],
        )
        assert job_titles.missing_domain_words(REQUIRED, big_four) == []
        assert job_titles.domain_depth(REQUIRED, big_four) == 1.0

    def test_assurance_reads_the_same_way(self):
        profile = _profile("Audit & Assurance Senior Manager", ["Assurance Manager"])
        assert job_titles.missing_domain_words(REQUIRED, profile) == []

    def test_an_explicitly_internal_auditor_is_still_not_one(self):
        internal = _profile("Internal Audit Manager", ["Internal Audit Manager"])
        assert job_titles.missing_domain_words(REQUIRED, internal) == ["external"]

    def test_a_profession_with_no_audit_at_all_is_unaffected(self):
        finance = _profile("Finance Manager", ["Finance Manager"])
        assert job_titles.missing_domain_words(REQUIRED, finance) == ["audit", "external"]

    def test_the_default_does_not_apply_to_unrelated_qualifiers(self):
        """Only professions with a genuinely unnamed default are listed."""
        profile = _profile("Backend Engineer", ["Backend Engineer"])
        assert job_titles.missing_domain_words("senior frontend engineer", profile) == [
            "frontend"
        ]
