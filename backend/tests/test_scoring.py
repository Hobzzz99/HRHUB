"""Tests for weighted scoring, breakdown, reasons, and versioning.

v2 weighting: title 30% + keywords 30% + experience 30% + location 10%.
Keywords are matched against the candidate's headline and job titles.
"""

from __future__ import annotations

import pytest

from app.domain.models import ExperienceItem, RawProfile, SearchCriteria
from app.domain.scoring import SCORE_VERSION, score_candidate


def _profile(**overrides) -> RawProfile:
    defaults = dict(
        source="mock",
        source_profile_url="https://example.com/in/jane",
        name="Jane Doe",
        headline="Senior Backend Engineer | Python and FastAPI",
        current_title="Backend Engineer",
        current_company="Acme",
        location="Berlin, Germany",
        skills=["Python", "FastAPI", "Docker", "AWS"],
        experience=[ExperienceItem(title="Backend Engineer", company="Acme")],
    )
    defaults.update(overrides)
    return RawProfile(**defaults)


def _criteria(**overrides) -> SearchCriteria:
    defaults = dict(
        job_title="Backend Engineer",
        keywords=["Python", "FastAPI"],
        location="Berlin",
        min_experience=5,
    )
    defaults.update(overrides)
    return SearchCriteria(**defaults)


def test_perfect_candidate_scores_100():
    scored = score_candidate(_profile(), _criteria(), total_years=8.0)
    assert scored.match_score == pytest.approx(100.0)
    assert scored.breakdown.title == 100.0
    assert scored.breakdown.keywords == 100.0
    assert scored.breakdown.experience == 100.0
    assert scored.breakdown.location == 100.0
    assert scored.score_version == SCORE_VERSION


def test_missing_keyword_lowers_the_keyword_component():
    criteria = _criteria(keywords=["Python", "FastAPI", "Kubernetes", "Terraform"])
    scored = score_candidate(_profile(), criteria, total_years=8.0)

    assert set(scored.matched_keywords) == {"Python", "FastAPI"}
    assert set(scored.missing_keywords) == {"Kubernetes", "Terraform"}
    assert scored.breakdown.keywords == pytest.approx(50.0)


def test_keywords_read_declared_fields_including_the_skills_list():
    # Docker appears in no title but is a listed skill, and listed skills are a
    # declared claim, so it counts.
    scored = score_candidate(_profile(), _criteria(keywords=["Docker"]), total_years=8.0)
    assert scored.matched_keywords == ["Docker"]
    assert scored.breakdown.keywords == 100.0


def test_keywords_ignore_prose():
    # The same term buried in the About section is not evidence of anything.
    profile = _profile(skills=[], about="I have used Kubernetes on a few projects.")
    scored = score_candidate(
        profile, _criteria(keywords=["Kubernetes"]), total_years=8.0
    )
    assert scored.missing_keywords == ["Kubernetes"]
    assert scored.breakdown.keywords == 0.0


def test_keyword_matches_a_past_job_title():
    profile = _profile(
        headline="Operations Lead",
        current_title="Operations Lead",
        experience=[
            ExperienceItem(title="Operations Lead", company="Acme"),
            ExperienceItem(title="Vendor Manager", company="Globex"),
        ],
    )
    scored = score_candidate(
        profile, _criteria(keywords=["vendor management"]), total_years=8.0
    )
    assert scored.matched_keywords == ["vendor management"]


def test_experience_below_minimum_scales_down():
    scored = score_candidate(_profile(), _criteria(min_experience=10), total_years=5.0)
    assert scored.breakdown.experience == pytest.approx(50.0)


def test_experience_is_capped_not_rewarded_for_overshooting():
    scored = score_candidate(_profile(), _criteria(min_experience=5), total_years=30.0)
    assert scored.breakdown.experience == 100.0


def test_reasons_mention_experience_and_keywords():
    scored = score_candidate(_profile(), _criteria(), total_years=8.0)
    joined = " | ".join(scored.reasons)
    assert "Job title strongly matches" in joined
    assert "meets 5 required" in joined
    assert "Title mentions Python" in joined
    assert "Location matches" in joined


def test_location_mismatch_zeroes_location_component():
    scored = score_candidate(
        _profile(location="Tokyo, Japan"), _criteria(location="Berlin"), total_years=8.0
    )
    assert scored.breakdown.location == 0.0
    # Total drops by exactly the 10% location weight from the perfect baseline.
    assert scored.match_score == pytest.approx(90.0)


def test_unstated_requirements_do_not_penalise():
    # Nothing but a title asked for. The unstated components are excluded from
    # the weighted total (see the redistribution test below) and still display
    # as 100, so a criterion nobody set can neither hurt nor help a candidate.
    criteria = SearchCriteria(job_title="Backend Engineer", min_experience=0)
    scored = score_candidate(_profile(), criteria, total_years=1.0)
    assert scored.breakdown.keywords == 100.0
    assert scored.breakdown.location == 100.0
    assert scored.match_score == pytest.approx(100.0)


def test_education_no_longer_contributes():
    """v2 dropped education; a profile with none must still be able to score 100."""
    scored = score_candidate(
        _profile(education=[], certifications=[], licenses=[]),
        _criteria(),
        total_years=8.0,
    )
    assert scored.match_score == pytest.approx(100.0)
    assert not hasattr(scored.breakdown, "education")


def test_weights_are_the_agreed_split_and_sum_to_one():
    from app.domain.scoring import WEIGHTS

    assert WEIGHTS == {
        "title": 0.30,
        "keywords": 0.30,
        "experience": 0.30,
        "location": 0.10,
    }
    assert sum(WEIGHTS.values()) == pytest.approx(1.0)


def test_an_unstated_component_is_dropped_not_given_full_marks():
    """Leaving a field blank must not hand every candidate free points.

    Awarding 1.0 for an unrequested criterion flattens the ranking and makes a
    score threshold mean different things depending on which boxes were filled
    in. The weight is redistributed across what was actually asked for.
    """
    weak = _profile(
        headline="Marketing Manager",
        current_title="Marketing Manager",
        experience=[ExperienceItem(title="Marketing Manager", company="Acme")],
        skills=[],
    )

    with_location = SearchCriteria(
        job_title="Backend Engineer", keywords=["python"],
        location="Berlin", min_experience=3,
    )
    without_location = SearchCriteria(
        job_title="Backend Engineer", keywords=["python"], min_experience=3,
    )

    scored_with = score_candidate(weak, with_location, total_years=8.0)
    scored_without = score_candidate(weak, without_location, total_years=8.0)

    # The candidate is in Berlin, so stating the location used to gift 10 points.
    assert scored_without.match_score < scored_with.match_score


def test_a_perfect_candidate_still_scores_100_with_fields_left_blank():
    criteria = SearchCriteria(job_title="Backend Engineer", keywords=["python"])
    assert score_candidate(_profile(), criteria, total_years=1.0).match_score == 100.0


def test_title_only_search_scores_purely_on_title():
    criteria = SearchCriteria(job_title="Backend Engineer")
    scored = score_candidate(_profile(), criteria, total_years=0.0)
    assert scored.match_score == pytest.approx(scored.breakdown.title)
