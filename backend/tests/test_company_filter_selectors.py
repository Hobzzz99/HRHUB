"""The filter pill is a div, not a button — and it arrives late.

Both facts came from debug dumps of real, signed-in searches:

* A fully rendered page (141k of HTML) contained "Current companies" and our
  selectors still matched nothing, because every one of them named the ``button``
  tag. LinkedIn renders ``<div role="button" aria-label="Filter by Current
  companies">``.
* Two later dumps (~50k) had no filter bar at all: results and pagination had
  drawn, the pills had not. A single immediate check called that a failure.

Either fault sends the search on unfiltered, which is how a Big Four search
returned people from AMSG, Nash CPAs and a petroleum company.
"""

from __future__ import annotations

from app.providers.company_filter import COMPANY, LOCATION, PILL_WAIT_S


class TestPillSelectorsMatchRealMarkup:
    def test_company_does_not_rely_on_the_button_tag(self):
        """At least one selector must match a div with role=button."""
        tag_free = [s for s in COMPANY.pill if not s.startswith("button")]
        assert tag_free, "every company pill selector requires a <button>"

    def test_location_does_not_rely_on_the_button_tag(self):
        tag_free = [s for s in LOCATION.pill if not s.startswith("button")]
        assert tag_free, "every location pill selector requires a <button>"

    def test_company_matches_by_aria_label(self):
        """aria-label is the stable hook; class names are build-hashed."""
        assert any("aria-label" in s and "Current compan" in s for s in COMPANY.pill)

    def test_location_matches_by_aria_label(self):
        assert any("aria-label" in s for s in LOCATION.pill)

    def test_role_button_selectors_come_before_tag_selectors(self):
        """Order decides which is tried first, and the div is what exists."""
        for facet in (COMPANY, LOCATION):
            first_tag = next(
                (i for i, s in enumerate(facet.pill) if s.startswith("button")), len(facet.pill)
            )
            first_role = next(
                (i for i, s in enumerate(facet.pill) if not s.startswith("button")),
                len(facet.pill),
            )
            assert first_role < first_tag, f"{facet.name}: tag selector tried first"


def test_the_pill_is_waited_for():
    """Results and pagination render before the filter bar does."""
    assert PILL_WAIT_S >= 10
