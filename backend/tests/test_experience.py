"""Tests for total experience calculation (merging, gaps, present, parsing)."""

from __future__ import annotations

from datetime import date

import pytest

from app.domain.experience import (
    compute_total_experience_years,
    parse_date_token,
    parse_range,
)
from app.domain.models import ExperienceItem

TODAY = date(2026, 1, 1)


def test_spec_example_earliest_to_present():
    # Junior 2018-2020, SWE 2020-2023, Backend 2023-Present → ~8 years.
    experiences = [
        ExperienceItem(title="Backend Engineer", start="2023", end="Present"),
        ExperienceItem(title="Software Engineer", start="2020", end="2023"),
        ExperienceItem(title="Junior Developer", start="2018", end="2020"),
    ]
    years = compute_total_experience_years(experiences, today=TODAY)
    assert years == pytest.approx(8.0, abs=0.05)


def test_overlapping_roles_not_double_counted():
    # Concurrent roles: 2020-2022 and 2021-2023 cover 2020-2023 = 3 years, not 4.
    experiences = [
        ExperienceItem(start="2020", end="2022"),
        ExperienceItem(start="2021", end="2023"),
    ]
    years = compute_total_experience_years(experiences, today=TODAY)
    assert years == pytest.approx(3.0, abs=0.05)


def test_career_gap_excluded():
    # 2010-2012 and 2020-2022 → 2 + 2 = 4 years (the 8-year gap is not counted).
    experiences = [
        ExperienceItem(start="2010", end="2012"),
        ExperienceItem(start="2020", end="2022"),
    ]
    years = compute_total_experience_years(experiences, today=TODAY)
    assert years == pytest.approx(4.0, abs=0.05)


def test_present_end_uses_today():
    experiences = [ExperienceItem(start="2024-01", end=None)]
    years = compute_total_experience_years(experiences, today=TODAY)
    assert years == pytest.approx(2.0, abs=0.05)


def test_unparseable_start_is_skipped():
    experiences = [
        ExperienceItem(start="???", end="2023"),
        ExperienceItem(start="2020", end="2022"),
    ]
    years = compute_total_experience_years(experiences, today=TODAY)
    assert years == pytest.approx(2.0, abs=0.05)


def test_empty_experience_is_zero():
    assert compute_total_experience_years([], today=TODAY) == 0.0


@pytest.mark.parametrize(
    "token,expected",
    [
        ("2020", date(2020, 1, 1)),
        ("2020-03", date(2020, 3, 1)),
        ("2020/03", date(2020, 3, 1)),
        ("Jan 2020", date(2020, 1, 1)),
        ("January 2020", date(2020, 1, 1)),
        ("2019-12-15", date(2019, 12, 1)),
        ("garbage", None),
    ],
)
def test_parse_date_token(token, expected):
    assert parse_date_token(token, today=TODAY) == expected


def test_parse_range_swaps_reversed_dates():
    item = ExperienceItem(start="2023", end="2020")
    start, end = parse_range(item, today=TODAY)
    assert start == date(2020, 1, 1)
    assert end == date(2023, 1, 1)
