"""A pasted LinkedIn URL carries both filters, and both must be used.

The paste-a-URL escape hatch read only `currentCompany` and silently dropped
`geoUrn`. A recruiter who filtered by firm *and* country on LinkedIn, then
pasted the result, got their companies applied and their location thrown away —
the app tried to drive the location panel itself, failed, and returned audit
managers from everywhere. The screen said the location filter could not be
applied, which was true and avoidable: LinkedIn had already resolved it.
"""

from __future__ import annotations

from app.domain.models import SearchCriteria
from app.providers.company_filter import COMPANY, LOCATION, ids_in_url
from app.providers.search_plan import plan

# Exactly what a recruiter pastes: audit managers, Saudi Arabia, 14 audit firms.
PASTED = (
    "https://www.linkedin.com/search/results/people/?keywords=audit%20manager"
    "&origin=FACETED_SEARCH&geoUrn=%5B%22100459316%22%5D"
    "&currentCompany=%5B%221038%22%2C%221073%22%2C%221044%22%5D"
)


class TestReadingBothFilters:
    def test_company_ids_are_read(self):
        assert ids_in_url(PASTED, COMPANY.url_param) == ["1038", "1073", "1044"]

    def test_location_ids_are_read(self):
        """The half that used to be dropped."""
        assert ids_in_url(PASTED, LOCATION.url_param) == ["100459316"]

    def test_a_url_without_a_location_yields_none(self):
        url = "https://www.linkedin.com/search/results/people/?currentCompany=%5B%221038%22%5D"
        assert ids_in_url(url, LOCATION.url_param) == []


class TestPlanning:
    def test_pasted_location_ids_plan_a_location_filter(self):
        """Even without the strict switch: the recruiter picked that location on
        LinkedIn itself, which is a more deliberate act than ticking a box."""
        criteria = SearchCriteria(job_title="audit manager", location_ids=["100459316"])
        assert [step.facet for step in plan(criteria)] == [LOCATION]

    def test_pasted_ids_for_both_plan_both(self):
        criteria = SearchCriteria(
            job_title="audit manager",
            company_ids=["1038"],
            location_ids=["100459316"],
        )
        facets = [step.facet for step in plan(criteria)]
        assert COMPANY in facets
        assert LOCATION in facets

    def test_a_plain_location_still_needs_the_strict_switch(self):
        """Typed free text without the switch stays a 10% preference, not a filter."""
        criteria = SearchCriteria(job_title="audit manager", location="Saudi Arabia")
        assert plan(criteria) == []

    def test_employer_is_still_never_released_when_widening(self):
        from app.providers.search_plan import relax

        criteria = SearchCriteria(
            job_title="audit manager",
            company_ids=["1038"],
            location_ids=["100459316"],
        )
        steps = plan(criteria)
        remaining, given_up = relax(steps)
        assert given_up is not None
        assert given_up.facet is LOCATION
        assert [s.facet for s in remaining] == [COMPANY]
