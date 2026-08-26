"""Total professional experience calculation.

Parses free-form role date ranges, builds intervals, **merges overlapping or
concurrent roles**, and sums the covered time. This is more correct than a naive
earliest-start-to-today span: it excludes career gaps and never double-counts two
jobs held at the same time.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import date

from app.domain.models import ExperienceItem

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
_PRESENT = {"present", "current", "now", "today", "ongoing", ""}
_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def parse_date_token(token: str | None, *, default_to_present: bool = False,
                     today: date | None = None) -> date | None:
    """Parse a single date token to the first day of its month.

    Returns ``None`` when the token is empty/"present" (unless
    ``default_to_present`` maps that to ``today``) or cannot be parsed.
    """
    today = today or date.today()
    if token is None:
        return today if default_to_present else None

    text = token.strip().lower()
    if text in _PRESENT:
        return today if default_to_present else None

    # ISO-ish: 2020-03-15 / 2020-03 / 2020/03
    iso = re.match(r"^(\d{4})[-/](\d{1,2})(?:[-/](\d{1,2}))?$", text)
    if iso:
        year, month = int(iso.group(1)), int(iso.group(2))
        if 1 <= month <= 12:
            return date(year, month, 1)

    # "Jan 2020" / "January 2020" / "2020 Jan"
    month = None
    for name, num in _MONTHS.items():
        if re.search(rf"\b{name}\b", text):
            month = num
            break
    year_match = _YEAR_RE.search(text)
    if year_match:
        year = int(year_match.group(0))
        return date(year, month or 1, 1)

    return None


def parse_range(item: ExperienceItem, *, today: date | None = None
                ) -> tuple[date, date] | None:
    """Return a ``(start, end)`` interval for a role, or ``None`` if unusable."""
    today = today or date.today()
    start = parse_date_token(item.start, today=today)
    if start is None:
        return None
    end = parse_date_token(item.end, default_to_present=True, today=today) or today
    if end < start:
        start, end = end, start
    return start, end


def _merge(intervals: list[tuple[date, date]]) -> list[tuple[date, date]]:
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [intervals[0]]
    for start, end in intervals[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:  # overlapping or touching → combine
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))
    return merged


def compute_total_experience_years(
    experiences: list[ExperienceItem], *, today: date | None = None
) -> float:
    """Total years of professional experience, merging overlaps and skipping gaps."""
    return _years(experiences, today=today)


def compute_relevant_experience_years(
    experiences: list[ExperienceItem],
    matches: Callable[[ExperienceItem], bool],
    *,
    today: date | None = None,
) -> float:
    """Years spent in the roles that count, rather than years alive in a career.

    "Ten years of external audit" and "ten years of anything, plus the words
    external audit somewhere" are very different requirements, and only the
    second was being measured. A finance director who audited for two years a
    decade ago satisfied the first reading of a 10-year bar; the audit manager
    with eight solid years did not.

    Overlaps are merged the same way, so someone holding two audit roles at once
    is credited with the calendar time, not twice over.
    """
    return _years([item for item in experiences if matches(item)], today=today)


def has_dated_roles(
    experiences: list[ExperienceItem], *, today: date | None = None
) -> bool:
    """Whether any role carries dates we can read.

    Without this, "years in the field" is indistinguishable from "no years in
    the field", and a profile whose dates failed to extract would be rejected
    for a requirement it may well meet.
    """
    today = today or date.today()
    return any(parse_range(item, today=today) is not None for item in experiences)


def _years(experiences: list[ExperienceItem], *, today: date | None = None) -> float:
    today = today or date.today()
    intervals = [
        interval
        for item in experiences
        if (interval := parse_range(item, today=today)) is not None
    ]
    total_days = sum((end - start).days for start, end in _merge(intervals))
    return round(total_days / 365.25, 1)
