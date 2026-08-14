"""Graduation years, used to filter by career stage.

Recruiters express "early career" as a graduation-year range far more naturally
than as a years-of-experience number, because it is the figure actually printed
on a profile. This module reads it back out.

**Which year counts.** A candidate's *earliest* completed education is the one
that marks entry to the workforce, so that is what a range is tested against.
Using the latest instead would let someone who finished a part-time MBA last
year read as a recent graduate despite thirty years of work behind them — the
opposite of what a career-stage filter is asked to do.
"""

from __future__ import annotations

import re
from datetime import date

from app.domain.models import EducationItem

#: A four-digit year that could plausibly be a graduation. Bounded so a stray
#: number on a profile ("Class of 12", a course code) is not read as a year.
_YEAR_RE = re.compile(r"\b(19[5-9]\d|20\d\d)\b")

#: Ceiling on how far ahead an expected graduation may sit. Students list a
#: future end year, which is legitimate; a date decades out is a parse error.
_MAX_YEARS_AHEAD = 8


def parse_year(text: str | None, *, today: date | None = None) -> int | None:
    """The graduation year in ``text``, or None when there isn't a usable one."""
    if not text:
        return None
    today = today or date.today()
    years = [int(m) for m in _YEAR_RE.findall(text)]
    plausible = [y for y in years if y <= today.year + _MAX_YEARS_AHEAD]
    # Latest within one entry: a range like "2015 - 2019" ends at graduation.
    return max(plausible) if plausible else None


def graduation_years(education: list[EducationItem], *, today: date | None = None) -> list[int]:
    """Every graduation year on the profile, oldest first."""
    years = [
        year
        for item in education
        if (year := parse_year(item.end or item.start, today=today)) is not None
    ]
    return sorted(years)


def first_graduation_year(
    education: list[EducationItem], *, today: date | None = None
) -> int | None:
    """The earliest graduation year — the proxy for entering the workforce."""
    years = graduation_years(education, today=today)
    return years[0] if years else None


def in_range(
    education: list[EducationItem],
    *,
    year_from: int | None = None,
    year_to: int | None = None,
    today: date | None = None,
) -> tuple[bool, str | None]:
    """Whether the first graduation falls inside the requested range.

    Returns ``(keep, reason_if_discarded)``.

    A profile with **no readable graduation year is kept**. LinkedIn education
    entries frequently omit dates, and a missing date is not evidence of the
    wrong career stage — rejecting on it would silently discard candidates for
    how they maintain their profile rather than for who they are.
    """
    if year_from is None and year_to is None:
        return True, None

    year = first_graduation_year(education, today=today)
    if year is None:
        return True, None

    if year_from is not None and year < year_from:
        return False, f"Graduated {year}, before {year_from}"
    if year_to is not None and year > year_to:
        return False, f"Graduated {year}, after {year_to}"
    return True, None
