"""Tests for the Apify provider's input building and defensive field mapping.

No network. Actor authors disagree on field names for the same data, so the
payloads below deliberately use *different* spellings of the same profile to pin
down that the mapping copes rather than depending on one actor's schema.
"""

from __future__ import annotations

import pytest

from app.domain.models import SearchCriteria, SearchHit
from app.domain.scoring import score_candidate
from app.providers.apify_linkedin import (
    ApifyLinkedInProvider,
    _experience_items,
    _profile_from_item,
    _profile_input,
    _profile_url,
    _search_input,
    _skill_names,
    _split_range,
)
from app.providers.base import ProfileUnavailableError
from app.providers.factory import get_provider

HIT = SearchHit(source_profile_url="https://www.linkedin.com/in/aya")

# Shape A — nested objects, "experiences"/"educations", skills as dicts.
PROFILE_A = {
    "linkedinUrl": "https://www.linkedin.com/in/aya",
    "firstName": "Aya",
    "lastName": "Hassan",
    "headline": "Senior Backend Engineer at Acme",
    "addressWithCountry": "Cairo, Egypt",
    "about": "Distributed systems and payments.",
    "experiences": [
        {
            "title": "Senior Backend Engineer",
            "subtitle": "Acme",
            "caption": "Jan 2019 - Present · 6 yrs",
        },
        {"title": "Backend Engineer", "subtitle": "Startup", "caption": "2016 - 2019"},
    ],
    "educations": [{"title": "Cairo University", "subtitle": "BSc, Computer Science"}],
    "skills": [{"title": "Python"}, {"title": "PostgreSQL"}, {"title": "Docker"}],
}

# Shape B — flat strings, "experience"/"education", skills as a plain list.
PROFILE_B = {
    "profileUrl": "https://www.linkedin.com/in/aya/",
    "fullName": "Aya Hassan",
    "occupation": "Senior Backend Engineer at Acme",
    "location": "Cairo, Egypt",
    "summary": "Distributed systems and payments.",
    "experience": [
        {
            "position": "Senior Backend Engineer",
            "companyName": "Acme",
            "startDate": "2019-01",
            "endDate": None,
        }
    ],
    "education": ["Cairo University"],
    "skills": ["Python", "PostgreSQL", "Docker"],
}


def test_factory_returns_apify():
    assert isinstance(get_provider("apify"), ApifyLinkedInProvider)


# --- actor inputs ----------------------------------------------------------


def test_search_input_carries_query_and_location():
    payload = _search_input(
        SearchCriteria(job_title="backend engineer", keywords=["fintech"], location="Cairo")
    )
    assert "backend engineer" in payload["searchQuery"]
    assert "fintech" in payload["searchQuery"]
    assert payload["location"] == "Cairo"


def test_profile_input_never_contains_a_cookie():
    """A session cookie is an account — the thing this provider exists to avoid."""
    payload = _profile_input(["https://www.linkedin.com/in/aya"])
    serialized = str(payload).lower()
    assert "cookie" not in serialized
    assert "li_at" not in serialized
    assert payload["profileUrls"] == ["https://www.linkedin.com/in/aya"]


# --- url handling ----------------------------------------------------------


@pytest.mark.parametrize(
    ("item", "expected"),
    [
        ({"linkedinUrl": "https://www.linkedin.com/in/aya"}, "https://www.linkedin.com/in/aya"),
        ({"profileUrl": "https://www.linkedin.com/in/aya/"}, "https://www.linkedin.com/in/aya"),
        ({"url": "https://www.linkedin.com/in/aya?trk=x"}, "https://www.linkedin.com/in/aya"),
        ({"publicIdentifier": "aya"}, "https://www.linkedin.com/in/aya"),
        ({"url": "https://example.com/aya"}, None),
        ({}, None),
    ],
)
def test_profile_url_variants(item, expected):
    assert _profile_url(item) == expected


# --- mapping copes with either actor's shape -------------------------------


@pytest.mark.parametrize("payload", [PROFILE_A, PROFILE_B], ids=["nested", "flat"])
def test_profile_maps_from_either_shape(payload):
    profile = _profile_from_item(payload, "https://www.linkedin.com/in/aya", HIT)
    assert profile.source == "linkedin"
    assert profile.name == "Aya Hassan"
    assert profile.headline == "Senior Backend Engineer at Acme"
    assert profile.location == "Cairo, Egypt"
    assert profile.about == "Distributed systems and payments."
    assert profile.skills[:3] == ["Python", "PostgreSQL", "Docker"]
    assert profile.experience[0].title == "Senior Backend Engineer"
    assert profile.experience[0].company == "Acme"
    assert profile.education[0].school == "Cairo University"


def test_location_maps_from_harvestapi_nested_shape():
    """The harvestapi actor wraps location in {linkedinText, parsed:{...}} — a real
    shape that returned None until _as_text learned it."""
    item = {
        "linkedinUrl": "https://www.linkedin.com/in/x",
        "fullName": "X Y",
        "location": {
            "linkedinText": "Cairo, Cairo, Egypt",
            "parsed": {"city": "Cairo", "country": "Egypt"},
        },
    }
    profile = _profile_from_item(item, "https://www.linkedin.com/in/x", HIT)
    assert profile.location == "Cairo, Cairo, Egypt"


def test_current_company_derived_from_experience_when_absent():
    profile = _profile_from_item(PROFILE_A, "https://www.linkedin.com/in/aya", HIT)
    assert profile.current_company == "Acme"


def test_mapping_falls_back_to_the_search_hit():
    """The profile actor may omit what the search card already told us."""
    hit = SearchHit(
        source_profile_url="https://www.linkedin.com/in/x",
        name="Known Name",
        headline="Known Headline",
        location="Cairo",
    )
    profile = _profile_from_item({}, "https://www.linkedin.com/in/x", hit)
    assert profile.name == "Known Name"
    assert profile.headline == "Known Headline"
    assert profile.location == "Cairo"


def test_empty_item_does_not_explode():
    profile = _profile_from_item({}, "https://www.linkedin.com/in/x", HIT)
    assert profile.name == "Unknown"
    assert profile.skills == []
    assert profile.experience == []


# --- date ranges -----------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Jan 2019 - Present · 6 yrs", ("Jan 2019", "Present")),
        ("2016 - 2019", ("2016", "2019")),
        ("Jan 2019 – Mar 2020", ("Jan 2019", "Mar 2020")),
        ("2020", ("2020", None)),
        (None, (None, None)),
    ],
)
def test_split_range(text, expected):
    assert _split_range(text) == expected


def test_experience_parses_a_combined_range_string():
    items = _experience_items(PROFILE_A)
    assert items[0].start == "Jan 2019"
    assert items[0].end == "Present"


def test_skills_accept_dicts_strings_and_csv():
    assert _skill_names({"skills": [{"title": "Go"}, "Rust"]}) == ["Go", "Rust"]
    assert _skill_names({"skills": "Go, Rust"}) == ["Go", "Rust"]
    assert _skill_names({}) == []


def test_skills_deduplicate():
    assert _skill_names({"skills": ["Go", "Go", "Rust"]}) == ["Go", "Rust"]


# --- the point: mapped profiles score for real -----------------------------


@pytest.mark.parametrize("payload", [PROFILE_A, PROFILE_B], ids=["nested", "flat"])
def test_mapped_profile_scores_meaningfully(payload):
    """The scraper's flat-30 failure was empty profiles, not broken scoring."""
    profile = _profile_from_item(payload, "https://www.linkedin.com/in/aya", HIT)
    criteria = SearchCriteria(
        job_title="backend engineer",
        keywords=["backend"],
        location="Cairo",
        min_experience=3,
    )
    scored = score_candidate(profile, criteria)
    assert scored.breakdown.title == 100.0
    assert scored.breakdown.keywords == 100.0
    assert scored.breakdown.location == 100.0
    assert scored.breakdown.experience == 100.0
    assert scored.match_score > 30  # the number that started all this
    assert scored.matched_keywords == ["backend"]


async def test_fetch_profile_raises_when_actor_returns_nothing(monkeypatch):
    provider = ApifyLinkedInProvider(token="x")

    async def _empty(actor, payload):
        return []

    monkeypatch.setattr(provider, "_run_actor", _empty)
    with pytest.raises(ProfileUnavailableError) as exc:
        await provider.fetch_profile(HIT)
    assert "no profile" in str(exc.value).lower()


async def test_fetch_profile_serves_inline_profile_without_a_second_run(monkeypatch):
    """A profile the search actor returned inline must not trigger a paid fetch."""
    provider = ApifyLinkedInProvider(token="x")
    provider._profiles[HIT.source_profile_url] = PROFILE_A

    async def _boom(actor, payload):  # a call here would mean we paid Apify again
        raise AssertionError("ran the actor for an already-cached profile")

    monkeypatch.setattr(provider, "_run_actor", _boom)
    profile = await provider.fetch_profile(HIT)
    assert profile.name == "Aya Hassan"


async def test_missing_token_is_a_clear_error(monkeypatch):
    # Isolate from any ambient APIFY_TOKEN: an empty explicit token falls back to
    # config by design, so the config token must be blanked to test the no-token path.
    monkeypatch.setattr("app.providers.apify_linkedin.settings.apify_token", "")
    provider = ApifyLinkedInProvider(token="")
    with pytest.raises(Exception) as exc:
        await provider.search(SearchCriteria(job_title="dev"))
    assert "APIFY_TOKEN" in str(exc.value)
