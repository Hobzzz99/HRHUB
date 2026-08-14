"""Tests for post-scoring filter rules."""

from __future__ import annotations

from app.domain.filtering import apply_filters
from app.domain.models import RawProfile, SearchCriteria
from app.domain.scoring import score_candidate


def _profile(**overrides) -> RawProfile:
    defaults = dict(
        source="mock",
        source_profile_url="https://example.com/in/jane",
        name="Jane Doe",
        current_title="Backend Engineer",
        location="Berlin",
        skills=["Python", "Docker"],
    )
    defaults.update(overrides)
    return RawProfile(**defaults)


def test_keeps_qualified_candidate():
    profile = _profile(skills=["Python", "FastAPI", "Docker", "AWS"])
    criteria = SearchCriteria(
        job_title="Backend Engineer",
        skills=["Python", "FastAPI", "Docker", "AWS"],
        min_experience=3,
    )
    scored = score_candidate(profile, criteria, total_years=6.0)
    decision = apply_filters(profile, scored, criteria)
    assert decision.keep is True
    assert decision.reasons == []


def test_discards_below_min_experience():
    profile = _profile()
    criteria = SearchCriteria(job_title="Backend Engineer", min_experience=5)
    scored = score_candidate(profile, criteria, total_years=2.0)
    decision = apply_filters(profile, scored, criteria)
    assert decision.keep is False
    assert any("experience" in r for r in decision.reasons)


def test_discards_missing_critical_skill():
    profile = _profile(skills=["Python"])
    criteria = SearchCriteria(
        job_title="Backend Engineer",
        skills=["Python", "Kubernetes"],
        critical_skills=["Kubernetes"],
    )
    scored = score_candidate(profile, criteria, total_years=6.0)
    decision = apply_filters(profile, scored, criteria)
    assert decision.keep is False
    assert any("critical" in r.lower() for r in decision.reasons)


def test_discards_below_score_threshold():
    profile = _profile(skills=[], current_title="Chef")
    criteria = SearchCriteria(
        job_title="Backend Engineer",
        keywords=["Python", "FastAPI"],
        min_match_score=50,
    )
    scored = score_candidate(profile, criteria, total_years=6.0)
    decision = apply_filters(profile, scored, criteria)
    assert decision.keep is False
    assert any("threshold" in r for r in decision.reasons)


def test_enforce_location_discards_wrong_location():
    profile = _profile(location="Tokyo")
    criteria = SearchCriteria(
        job_title="Backend Engineer", location="Berlin", enforce_location=True
    )
    scored = score_candidate(profile, criteria, total_years=6.0)
    decision = apply_filters(profile, scored, criteria)
    assert decision.keep is False
