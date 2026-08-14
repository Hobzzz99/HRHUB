"""Deciding which LinkedIn filters to apply, and what to do when they bite too hard.

A recruiter does not apply every filter they can and accept whatever falls out.
They filter hard, look at how much is left, and if the list is too thin they
loosen the least important constraint and look again. This module encodes that
judgement so the scraper behaves the same way.

Two decisions live here, and both are pure — no browser, no network — so they
can be reasoned about and tested directly:

* **What to filter on.** Only what the recruiter actually stated, applied
  through LinkedIn's own facets rather than folded into the search text.
* **What to give up first** when a search returns too little. Constraints are
  ordered by how central they are to the request, and the least central is
  released first — never the one the recruiter clearly cared about most.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.domain.models import SearchCriteria
from app.providers.company_filter import COMPANY, LOCATION, Facet


@dataclass(frozen=True, slots=True)
class FilterStep:
    """One facet to apply, and how readily it may be given up."""

    facet: Facet
    values: list[str]
    #: Lower is more important. The highest number is released first.
    give_up_order: int
    #: Shown to the operator when it is released.
    label: str
    #: Some constraints *are* the search. Widening past them would answer a
    #: different question than the one asked.
    relaxable: bool = True

    @property
    def url_param(self) -> str:
        return self.facet.url_param


def plan(criteria: SearchCriteria) -> list[FilterStep]:
    """The filters to apply for this search, most important first.

    Employer outranks location deliberately. Someone searching the Big Four is
    making a statement about *who they want*; the city is usually a preference
    around it. Widening the map keeps the search meaningful, whereas dropping
    the employer turns it into a different search entirely.
    """
    steps: list[FilterStep] = []

    if criteria.companies or criteria.company_ids:
        steps.append(
            FilterStep(
                facet=COMPANY,
                values=list(criteria.companies),
                give_up_order=1,
                # Never traded away: a recruiter who asked for the Big Four does
                # not want a longer list of people from elsewhere.
                relaxable=False,
                label="employer",
            )
        )
    # Only when the recruiter made location a hard requirement. A location set
    # without the strict switch is a *preference* worth 10% of the score, and
    # turning it into a server-side filter would quietly promote it to a
    # requirement — hiding candidates the recruiter said they would still
    # consider.
    if criteria.enforce_location and criteria.location:
        steps.append(
            FilterStep(
                facet=LOCATION,
                values=[criteria.location],
                give_up_order=2,  # released first
                label="location",
            )
        )
    return steps


def too_thin(found: int, wanted: int) -> bool:
    """Whether a filtered search returned so little it is worth loosening.

    Half of what was asked for is the trigger. Below that a recruiter stops
    trusting the filters and widens; above it they work with what they have
    rather than diluting the shortlist for the sake of length.
    """
    if wanted <= 0:
        return False
    return found < max(1, wanted // 2)


def relax(steps: list[FilterStep]) -> tuple[list[FilterStep], FilterStep | None]:
    """Release the least important remaining filter.

    Returns the reduced plan and whichever step was given up, so the decision
    can be reported rather than silently changing what the recruiter asked for.
    """
    candidates = [step for step in steps if step.relaxable]
    if not candidates:
        return steps, None
    victim = max(candidates, key=lambda step: step.give_up_order)
    return [step for step in steps if step is not victim], victim


def describe(steps: list[FilterStep]) -> str:
    """A short human-readable summary of the plan, for logs and progress."""
    if not steps:
        return "no filters"
    return ", ".join(f"{s.label}={'+'.join(s.values) or 'set'}" for s in steps)
