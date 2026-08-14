"""Tests for the conservative pre-filter (only discards clear mismatches)."""

from __future__ import annotations

from app.domain.models import SearchCriteria, SearchHit
from app.domain.prefilter import passes_prefilter


def test_keeps_by_default():
    hit = SearchHit(source_profile_url="u", headline="Backend Engineer", location="Berlin")
    keep, reason = passes_prefilter(hit, SearchCriteria(job_title="Backend Engineer"))
    assert keep is True
    assert reason is None


def test_title_mismatch_alone_is_kept():
    # Headline undersells the candidate — must NOT be discarded pre-scoring.
    hit = SearchHit(source_profile_url="u", headline="CTO", location="Berlin")
    keep, _ = passes_prefilter(
        hit, SearchCriteria(job_title="Backend Engineer", location="Berlin")
    )
    assert keep is True


def test_location_mismatch_discarded_only_when_enforced():
    hit = SearchHit(source_profile_url="u", location="Tokyo, Japan")
    criteria = SearchCriteria(
        job_title="Backend Engineer", location="Berlin", enforce_location=True
    )
    keep, reason = passes_prefilter(hit, criteria)
    assert keep is False
    assert reason and "Location" in reason


def test_location_mismatch_kept_when_not_enforced():
    hit = SearchHit(source_profile_url="u", location="Tokyo, Japan")
    criteria = SearchCriteria(job_title="Backend Engineer", location="Berlin")
    keep, _ = passes_prefilter(hit, criteria)
    assert keep is True


def test_remote_never_discarded_on_location():
    hit = SearchHit(source_profile_url="u", location="Remote")
    criteria = SearchCriteria(
        job_title="Backend Engineer", location="Berlin", enforce_location=True
    )
    keep, _ = passes_prefilter(hit, criteria)
    assert keep is True


def test_company_mismatch_discarded():
    hit = SearchHit(source_profile_url="u", current_company="Globex")
    criteria = SearchCriteria(job_title="Backend Engineer", companies=["Acme"])
    keep, reason = passes_prefilter(hit, criteria)
    assert keep is False
    assert reason and "Company" in reason


def test_any_of_several_requested_employers_is_kept():
    """Filtering on the Big Four must keep somebody at any one of them."""
    hit = SearchHit(source_profile_url="u", current_company="Ernst & Young LLP")
    criteria = SearchCriteria(
        job_title="Audit Manager", companies=["Deloitte", "PwC", "EY", "KPMG"]
    )
    assert passes_prefilter(hit, criteria)[0]


def test_a_card_without_a_company_is_never_discarded():
    # The pre-filter runs on shallow card data and must only reject clear
    # mismatches; a missing employer is not evidence of the wrong employer.
    hit = SearchHit(source_profile_url="u", current_company=None)
    criteria = SearchCriteria(job_title="Audit Manager", companies=["Deloitte"])
    assert passes_prefilter(hit, criteria)[0]
