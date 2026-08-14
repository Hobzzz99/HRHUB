"""Which filters a search applies, and which it gives up when results are thin.

Pure decision logic — no browser — because this is the judgement the scraper is
being asked to make on its own, and it should be inspectable.
"""

from __future__ import annotations

import pytest

from app.domain.models import SearchCriteria
from app.providers.company_filter import COMPANY, LOCATION
from app.providers.search_plan import describe, plan, relax, too_thin


def test_only_what_the_recruiter_stated_is_filtered_on():
    steps = plan(SearchCriteria(job_title="audit manager"))
    assert steps == []


def test_employer_and_strict_location_each_become_a_filter():
    criteria = SearchCriteria(
        job_title="audit manager",
        companies=["Deloitte", "EY"],
        location="Egypt",
        enforce_location=True,
    )
    facets = {step.facet for step in plan(criteria)}
    assert facets == {COMPANY, LOCATION}


def test_a_soft_location_is_not_turned_into_a_hard_filter():
    """Without the strict switch, location is a 10% preference, not a requirement.

    Filtering LinkedIn by it would silently promote it — hiding candidates the
    recruiter explicitly said they would still consider.
    """
    criteria = SearchCriteria(
        job_title="audit manager", companies=["Deloitte"], location="Egypt"
    )
    assert [s.facet for s in plan(criteria)] == [COMPANY]


def test_pasted_company_ids_still_produce_a_filter_step():
    criteria = SearchCriteria(job_title="audit manager", company_ids=["1038"])
    assert [s.facet for s in plan(criteria)] == [COMPANY]


def test_location_is_given_up_before_employer():
    """Searching the Big Four is a statement about who; the city is a preference.

    Widening the map keeps the search meaningful. Dropping the employer would
    make it a different search entirely.
    """
    criteria = SearchCriteria(
        job_title="audit manager",
        companies=["Deloitte"],
        location="Egypt",
        enforce_location=True,
    )
    remaining, given_up = relax(plan(criteria))
    assert given_up.label == "location"
    assert [s.label for s in remaining] == ["employer"]


def test_relaxing_continues_until_nothing_is_left():
    criteria = SearchCriteria(
        job_title="audit manager",
        companies=["Deloitte"],
        location="Egypt",
        enforce_location=True,
    )
    steps = plan(criteria)
    steps, first = relax(steps)
    steps, second = relax(steps)

    # Location goes; the employer never does. Widening past the employer would
    # answer a different question than the one the recruiter asked.
    assert first.label == "location"
    assert second is None
    assert [s.label for s in steps] == ["employer"]


@pytest.mark.parametrize(
    ("found", "wanted", "expected"),
    [
        (0, 10, True),    # nothing came back
        (4, 10, True),    # under half
        (5, 10, False),   # half is enough to work with
        (10, 10, False),
        (3, 5, False),    # half of 5 rounds down to 2
        (1, 5, True),
        (0, 0, False),    # nothing asked for, nothing to widen
    ],
)
def test_when_a_result_set_counts_as_too_thin(found, wanted, expected):
    assert too_thin(found, wanted) is expected


def test_the_plan_reads_back_for_the_log():
    criteria = SearchCriteria(
        job_title="audit manager",
        companies=["Deloitte", "EY"],
        location="Egypt",
        enforce_location=True,
    )
    text = describe(plan(criteria))
    assert "employer=Deloitte+EY" in text
    assert "location=Egypt" in text
    assert describe([]) == "no filters"
