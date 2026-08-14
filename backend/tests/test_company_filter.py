"""Reading LinkedIn's company facet back out of a search URL, and label matching.

The URL forms here are taken from a real signed-in session, not invented.
"""

from __future__ import annotations

import json

import pytest

from app.providers.company_filter import (
    CompanyIdCache,
    _label_pattern,
    company_ids_in_url,
)

# Exactly as LinkedIn emits it after applying a three-firm filter.
REAL_URL = (
    "https://www.linkedin.com/search/results/people/"
    "?keywords=financial%20reporting%20supervisor&origin=GLOBAL_SEARCH_HEADER"
    '&currentCompany=%5B"9499295"%2C"1073"%2C"1038"%5D'
)


def test_ids_are_read_from_a_real_linkedin_url():
    assert company_ids_in_url(REAL_URL) == ["9499295", "1073", "1038"]


def test_ids_are_read_from_the_plain_address_bar_form():
    plain = (
        "https://www.linkedin.com/search/results/people/"
        '?currentCompany=["9499295","1073","1038"]'
    )
    assert company_ids_in_url(plain) == ["9499295", "1073", "1038"]


def test_a_single_company_url_still_parses():
    url = 'https://www.linkedin.com/search/results/people/?currentCompany=%5B"1038"%5D'
    assert company_ids_in_url(url) == ["1038"]


@pytest.mark.parametrize(
    "url",
    [
        "https://www.linkedin.com/search/results/people/?keywords=audit",
        "https://www.linkedin.com/feed/",
        "",
    ],
)
def test_urls_without_the_facet_yield_nothing(url):
    assert company_ids_in_url(url) == []


@pytest.mark.parametrize(
    ("requested", "label", "expected"),
    [
        ("KPMG", "KPMG Middle East", True),   # regional entity is the right one
        ("Deloitte", "Deloitte", True),
        ("EY", "EY", True),
        ("EY", "Honeywell", False),           # substring, not a word
        ("EY", "Key Bank", False),
        ("PwC", "PwC Middle East", True),
        ("Deloitte", "Grant Thornton", False),
    ],
)
def test_checkbox_labels_match_the_right_firm(requested, label, expected):
    assert bool(_label_pattern(requested).search(label)) is expected


def test_cache_round_trips_and_splits_known_from_missing(tmp_path):
    # Keys are namespaced per facet, so a city and an employer of the same name
    # cannot collide — "Deloitte" the company is not "Deloitte" the location.
    cache = CompanyIdCache(tmp_path / "ids.json")
    cache.put("company:Deloitte", "1038")

    known, missing = cache.known(["Deloitte", "KPMG", "  "], "company")
    assert known == ["1038"]
    assert missing == ["KPMG"]
    assert cache.get("  company:deloitte  ") == "1038"   # key is normalised


def test_the_same_name_in_two_facets_does_not_collide(tmp_path):
    cache = CompanyIdCache(tmp_path / "ids.json")
    cache.put("company:Georgia", "111")
    cache.put("location:Georgia", "222")

    assert cache.known(["Georgia"], "company") == (["111"], [])
    assert cache.known(["Georgia"], "location") == (["222"], [])


def test_cache_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "ids.json"
    path.write_text("{ this is not json", encoding="utf-8")
    cache = CompanyIdCache(path)
    assert cache.get("Deloitte") is None
    cache.put("company:Deloitte", "1038")
    assert json.loads(path.read_text(encoding="utf-8"))["company:deloitte"] == "1038"
