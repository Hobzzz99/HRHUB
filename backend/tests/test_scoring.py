"""Tests for weighted scoring, breakdown, reasons, and versioning."""

from __future__ import annotations

import pytest

from app.domain.models import EducationItem, RawProfile, SearchCriteria
from app.domain.scoring import SCORE_VERSION, score_candidate


def _profile(**overrides) -> RawProfile:
    defaults = dict(
        source="mock",
        source_profile_url="https://example.com/in/jane",
        name="Jane Doe",
        headline="Senior Backend Engineer",
        current_title="Backend Engineer",
        current_company="Acme",
        location="Berlin, Germany",
        skills=["Python", "FastAPI", "Docker", "AWS"],
        education=[EducationItem(school="TU Berlin", degree="BSc")],
        certifications=[{"name": "AWS Certified"}],
    )
    defaults.update(overrides)
    return RawProfile(**defaults)


def _criteria(**overrides) -> SearchCriteria:
    defaults = dict(
        job_title="Backend Engineer",
        skills=["Python", "FastAPI", "Docker", "AWS"],
        location="Berlin",
        min_experience=5,
    )
    defaults.update(overrides)
    return SearchCriteria(**defaults)


def test_perfect_candidate_scores_100():
    scored = score_candidate(_profile(), _criteria(), total_years=8.0)
    assert scored.match_score == pytest.approx(100.0)
    assert scored.breakdown.title == 100.0
    assert scored.breakdown.skills == 100.0
    assert scored.breakdown.experience == 100.0
    assert scored.breakdown.location == 100.0
    assert scored.breakdown.education == 100.0
    assert scored.score_version == SCORE_VERSION


def test_missing_skill_appears_in_missing_and_lowers_skill_score():
    criteria = _criteria(skills=["Python", "FastAPI", "Docker", "AWS", "Kubernetes"])
    scored = score_candidate(_profile(), criteria, total_years=8.0)
    assert "Kubernetes" in scored.missing_skills
    assert set(scored.matched_skills) == {"Python", "FastAPI", "Docker", "AWS"}
    assert scored.breakdown.skills == pytest.approx(80.0)


def test_experience_below_minimum_scales_down():
    scored = score_candidate(_profile(), _criteria(min_experience=10), total_years=5.0)
    assert scored.breakdown.experience == pytest.approx(50.0)


def test_reasons_mention_experience_and_skills():
    scored = score_candidate(_profile(), _criteria(), total_years=8.0)
    joined = " | ".join(scored.reasons)
    assert "Job title strongly matches" in joined
    assert "meets 5 required" in joined
    assert "Has Python" in joined
    assert "Location matches" in joined


def test_location_mismatch_zeroes_location_component():
    scored = score_candidate(
        _profile(location="Tokyo, Japan"), _criteria(location="Berlin"), total_years=8.0
    )
    assert scored.breakdown.location == 0.0
    # Total drops by the 10% location weight from the perfect baseline.
    assert scored.match_score == pytest.approx(90.0)


def test_weights_sum_to_one():
    from app.domain.scoring import WEIGHTS

    assert sum(WEIGHTS.values()) == pytest.approx(1.0)
