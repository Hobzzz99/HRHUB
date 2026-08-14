"""Employer matching — the fallback when LinkedIn's own facet cannot be applied.

The cases that matter are the ones where the name a recruiter types and the name
on a profile card are not the same string: EY / Ernst & Young, PwC /
PricewaterhouseCoopers, Deloitte / Deloitte & Touche.
"""

from __future__ import annotations

import pytest

from app.domain.companies import BIG_FOUR, matches


@pytest.mark.parametrize(
    ("requested", "card"),
    [
        ("Deloitte", "Deloitte"),
        ("Deloitte", "Deloitte & Touche LLP"),
        ("EY", "Ernst & Young"),
        ("EY", "Ernst & Young LLP"),
        ("Ernst & Young", "EY"),
        ("PwC", "PricewaterhouseCoopers"),
        ("PricewaterhouseCoopers", "PwC Middle East"),
        ("KPMG", "KPMG Al Fozan & Partners"),
        ("kpmg", "KPMG"),  # case-insensitive
    ],
)
def test_firms_that_should_match(requested, card):
    assert matches([requested], card)


@pytest.mark.parametrize(
    ("requested", "card"),
    [
        ("Deloitte", "KPMG"),
        ("EY", "Deloitte"),
        ("KPMG", "PwC"),
        ("PwC", "Grant Thornton"),
    ],
)
def test_firms_that_should_not_match(requested, card):
    assert not matches([requested], card)


def test_any_of_the_requested_firms_counts():
    assert matches(list(BIG_FOUR), "Ernst & Young LLP")
    assert not matches(list(BIG_FOUR), "Grant Thornton")


def test_no_company_requested_matches_everyone():
    # A filter nobody set must not exclude anyone.
    assert matches([], "Grant Thornton")


def test_a_card_with_no_company_is_kept():
    # LinkedIn frequently omits the employer on a card. Rejecting on missing
    # data would silently drop people who do work there — and the pre-filter is
    # deliberately the timid stage.
    assert matches(["Deloitte"], None)
    assert matches(["Deloitte"], "")


def test_legal_suffixes_do_not_defeat_a_match():
    assert matches(["Deloitte"], "Deloitte Limited")
    assert matches(["KPMG"], "KPMG Global Services Ltd")


# --- the guarantee: only the requested employers may appear -----------------


def test_an_unknown_employer_is_kept_on_a_card_but_rejected_on_a_profile():
    """The same absent employer means different things at different stages.

    On a search card it is missing data, and rejecting there would discard
    people who do work at the firm before we ever look. On a fetched profile we
    know the employer, so "only the Big Four" has to mean exactly that.
    """
    assert matches(["Deloitte"], None) is True                       # card
    assert matches(["Deloitte"], None, allow_unknown=False) is False  # profile
    assert matches(["Deloitte"], "", allow_unknown=False) is False


def test_a_matching_employer_passes_the_strict_check():
    assert matches(list(BIG_FOUR), "Ernst & Young LLP", allow_unknown=False)
    assert not matches(list(BIG_FOUR), "Grant Thornton", allow_unknown=False)
