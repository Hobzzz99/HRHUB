"""Nationality is evidence, never a verdict.

LinkedIn has no nationality field, so this is worked out from where somebody
studied. Three states matter, and conflating any two of them causes real harm:

* **Evidence** — a Saudi university on the profile. Keep.
* **Contradicted** — education is readable and none of it is Saudi. Reject.
* **Unknown** — no education on the profile at all. Keep, and say so.

That last one is the common case, not the edge case: education was readable on
102 of the 237 profiles in the real archive, and on *none* of the sixteen based
in Saudi Arabia. Rejecting on it would have discarded well over half of every
shortlist for a gap in extraction rather than a fact about the person.
"""

from __future__ import annotations

from app.domain import nationality
from app.domain.filtering import apply_filters
from app.domain.models import EducationItem, ExperienceItem, RawProfile, SearchCriteria
from app.domain.scoring import score_candidate


def _profile(*, schools: list[str] | None = None, headline: str = "Audit Manager", **over):
    base = dict(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name="Candidate",
        headline=headline,
        current_title="Audit Manager",
        current_company="PwC Middle East",
        experience=[ExperienceItem(title="External Auditor", company="PwC")],
        education=[EducationItem(school=s) for s in (schools or [])],
    )
    base.update(over)
    return RawProfile(**base)


class TestEvidence:
    def test_a_saudi_university_is_evidence(self):
        signal = nationality.assess(_profile(schools=["King Saud University"]), "Saudi Arabia")
        assert signal.likely
        assert "King Saud University" in signal.evidence[0]

    def test_spelling_variants_of_the_same_university(self):
        for name in ("King Abdulaziz University", "King Abdul Aziz University, Jeddah"):
            assert nationality.assess(_profile(schools=[name]), "Saudi Arabia").likely

    def test_self_declaration_counts(self):
        profile = _profile(headline="Audit Manager | Saudi National")
        assert nationality.assess(profile, "Saudi Arabia").likely

    def test_an_international_intake_university_is_weak_on_its_own(self):
        """KAUST's intake is largely international, so attendance proves little."""
        signal = nationality.assess(
            _profile(schools=["King Abdullah University of Science and Technology"]),
            "Saudi Arabia",
        )
        assert not signal.likely
        assert "weak evidence" in signal.evidence[0]


class TestTheThreeStates:
    def test_studying_elsewhere_is_a_contradiction(self):
        signal = nationality.assess(_profile(schools=["Ain Shams University"]), "Saudi Arabia")
        assert signal.contradicted
        assert not signal.unknown

    def test_no_education_at_all_is_unknown_not_a_contradiction(self):
        signal = nationality.assess(_profile(schools=[]), "Saudi Arabia")
        assert signal.unknown
        assert not signal.contradicted

    def test_working_in_the_country_is_not_evidence_of_being_from_it(self):
        """The distinction the whole feature exists for. Gulf audit practices
        are staffed heavily by expatriates."""
        profile = _profile(
            schools=["Cairo University"],
            location="Riyadh, Saudi Arabia",
            current_company="PwC Saudi Arabia",
        )
        assert nationality.assess(profile, "Saudi Arabia").contradicted

    def test_an_unsupported_country_is_reported_rather_than_guessed(self):
        signal = nationality.assess(_profile(schools=["Some University"]), "Atlantis")
        assert signal.unsupported
        assert not nationality.can_assess("Atlantis")
        assert nationality.can_assess("Saudi Arabia")


class TestFiltering:
    def _decide(self, profile, nationality_required="Saudi Arabia"):
        criteria = SearchCriteria(
            job_title="audit manager", nationality=nationality_required, min_match_score=0
        )
        return apply_filters(profile, score_candidate(profile, criteria), criteria)

    def test_a_saudi_graduate_is_kept(self):
        assert self._decide(_profile(schools=["King Saud University"])).keep

    def test_someone_who_studied_elsewhere_is_rejected(self):
        decision = self._decide(_profile(schools=["Ain Shams University"]))
        assert not decision.keep
        assert any("Saudi Arabia" in r for r in decision.reasons)

    def test_a_profile_with_no_education_is_kept(self):
        """Rejecting here would discard most of every shortlist for an
        extraction gap rather than anything about the candidate."""
        assert self._decide(_profile(schools=[])).keep

    def test_an_unverified_candidate_is_labelled_as_such(self):
        """A filtered list must not look verified when it is not."""
        criteria = SearchCriteria(job_title="audit manager", nationality="Saudi Arabia")
        scored = score_candidate(_profile(schools=[]), criteria)
        assert any("unverified" in r for r in scored.reasons)

    def test_the_evidence_travels_with_a_kept_candidate(self):
        criteria = SearchCriteria(job_title="audit manager", nationality="Saudi Arabia")
        scored = score_candidate(_profile(schools=["Umm Al-Qura University"]), criteria)
        assert any("Umm Al-Qura" in r for r in scored.reasons)

    def test_no_nationality_asked_means_no_filtering_and_no_noise(self):
        criteria = SearchCriteria(job_title="audit manager", min_match_score=0)
        profile = _profile(schools=["Ain Shams University"])
        scored = score_candidate(profile, criteria)
        assert apply_filters(profile, scored, criteria).keep
        assert not any("nationality" in r.lower() for r in scored.reasons)
