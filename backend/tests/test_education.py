"""Graduation-year parsing and the career-stage window."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.education import (
    first_graduation_year,
    graduation_years,
    in_range,
    parse_year,
)
from app.domain.models import EducationItem

TODAY = date(2026, 8, 5)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2019", 2019),
        ("2015 - 2019", 2019),          # a range ends at graduation
        ("Jun 2019", 2019),
        ("2019 – 2023", 2023),
        ("Class of 2021", 2021),
        ("2028", 2028),                 # a current student's expected year
        ("", None),
        (None, None),
        ("Class of 12", None),          # two digits is not a year
        ("2099", None),                 # implausibly far ahead
        ("1948", None),                 # before the accepted floor
    ],
)
def test_year_parsing(text, expected):
    assert parse_year(text, today=TODAY) == expected


def _edu(*ends: str) -> list[EducationItem]:
    return [EducationItem(school="S", end=e) for e in ends]


def test_earliest_graduation_is_what_counts():
    # A part-time MBA finished last year must not make a long career read as new.
    education = _edu("2005", "2024")
    assert graduation_years(education, today=TODAY) == [2005, 2024]
    assert first_graduation_year(education, today=TODAY) == 2005


def test_no_education_yields_no_year():
    assert first_graduation_year([], today=TODAY) is None


@pytest.mark.parametrize(
    ("ends", "keep"),
    [
        (("2021",), True),          # inside the window
        (("2019",), True),          # on the boundary
        (("2018",), False),         # a year too early
        (("2005", "2024"), False),  # earliest counts, not the recent MBA
        (("2026",), True),
    ],
)
def test_window_from_2019_onwards(ends, keep):
    got, reason = in_range(_edu(*ends), year_from=2019, today=TODAY)
    assert got is keep
    assert (reason is None) is keep


def test_an_upper_bound_also_applies():
    assert in_range(_edu("2024"), year_to=2020, today=TODAY)[0] is False
    assert in_range(_edu("2018"), year_to=2020, today=TODAY)[0] is True


def test_no_window_requested_keeps_everyone():
    assert in_range(_edu("1990"), today=TODAY) == (True, None)


def test_a_profile_without_dates_is_kept():
    """LinkedIn education entries often omit dates.

    A missing year is not evidence of the wrong career stage, and rejecting on
    it would discard candidates for how they maintain a profile rather than for
    anything about them.
    """
    assert in_range([EducationItem(school="S")], year_from=2019, today=TODAY) == (True, None)
    assert in_range([], year_from=2019, today=TODAY) == (True, None)


def test_the_discard_reason_names_the_year():
    _, reason = in_range(_edu("2010"), year_from=2019, today=TODAY)
    assert "2010" in reason and "2019" in reason
