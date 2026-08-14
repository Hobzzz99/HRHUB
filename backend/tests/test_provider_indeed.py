"""Indeed provider: contract, URL building, per-platform isolation, parsing.

Nothing here touches the network. What can be tested without a live employer
session is tested; the extraction selectors themselves are calibrated from a
`_debug/` dump on the first real run, which is why they are documented as
unverified rather than asserted here.
"""

from __future__ import annotations

import pytest

from app.domain.models import SearchCriteria
from app.providers.base import CandidateProvider
from app.providers.factory import SCRAPING_PLATFORM, SCRAPING_PROVIDERS, get_provider
from app.providers.indeed import IndeedProvider, _split_dates
from app.providers.rate_limit import budget_for


def test_the_factory_builds_it_and_treats_it_as_a_scraping_provider():
    provider = get_provider("indeed")
    assert isinstance(provider, IndeedProvider)
    assert isinstance(provider, CandidateProvider)
    assert "indeed" in SCRAPING_PROVIDERS
    assert SCRAPING_PLATFORM["indeed"] == "indeed"


def test_it_reports_a_budget_like_the_other_scraping_providers():
    snapshot = get_provider("indeed").budget()
    assert snapshot.limit > 0
    assert 0 <= snapshot.remaining <= snapshot.limit


def test_each_platform_has_its_own_budget(tmp_path, monkeypatch):
    """A busy LinkedIn run must not starve Indeed, or vice versa.

    The limit protects one account on one site; it is not a global throughput
    cap, so the two windows are counted separately.
    """
    from app.core.config import settings

    monkeypatch.setattr(settings, "scrape_state_dir", str(tmp_path))
    linkedin = budget_for("linkedin")
    indeed = budget_for("indeed")

    import asyncio

    asyncio.run(linkedin.acquire())
    assert linkedin.snapshot().used == 1
    assert indeed.snapshot().used == 0, "spending LinkedIn budget must not spend Indeed's"


def test_search_url_carries_query_and_location():
    url = IndeedProvider._search_url("audit manager external audit", "Riyadh", 1)
    assert url.startswith("https://resumes.indeed.com/search?q=")
    assert "audit+manager+external+audit" in url
    assert "l=Riyadh" in url
    assert "start=" not in url, "page 1 needs no offset"


def test_search_url_pages_by_offset_not_page_number():
    # Indeed pages resumes in blocks of 50 by `start`, unlike LinkedIn's `page`.
    assert "start=50" in IndeedProvider._search_url("audit", None, 2)
    assert "start=100" in IndeedProvider._search_url("audit", None, 3)


def test_search_url_omits_a_blank_location():
    for blank in (None, "", "   "):
        assert "&l=" not in IndeedProvider._search_url("audit", blank, 1)


def test_the_query_is_title_plus_keywords():
    criteria = SearchCriteria(
        job_title="Audit Manager", keywords=["external audit", "CPA"], location="Cairo"
    )
    query = IndeedProvider()._query(criteria)
    assert query == "Audit Manager external audit CPA"
    # Location is a separate parameter on Indeed, not part of the keyword text.
    assert "Cairo" not in query


@pytest.mark.parametrize(
    ("url", "login", "blocked", "challenge"),
    [
        ("https://resumes.indeed.com/search?q=x", False, False, False),
        ("https://secure.indeed.com/auth", True, False, False),
        ("https://resumes.indeed.com/account-suspended", False, True, False),
        ("https://resumes.indeed.com/subscription-required", False, True, False),
        ("https://resumes.indeed.com/challenge", False, False, True),
    ],
)
def test_page_state_is_read_from_the_url(url, login, blocked, challenge):
    assert IndeedProvider._is_login(url) is login
    assert IndeedProvider._is_blocked(url) is blocked
    assert IndeedProvider._is_challenge(url) is challenge


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("January 2020 to Present", ("January 2020", "Present")),
        ("2015 - 2019", ("2015", "2019")),
        ("2015 – 2019", ("2015", "2019")),
        ("2021", ("2021", None)),
        (None, (None, None)),
        ("", (None, None)),
    ],
)
def test_date_ranges_parse(text, expected):
    assert _split_dates(text) == expected
