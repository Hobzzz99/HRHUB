"""Keyword matching against headline and job titles.

The 30% keyword component. These cases are the ones that decide whether a real
LinkedIn search feels accurate, so they are enumerated explicitly:
exact / plural / word-form drift / multi-word / stopword-only / absent.
"""

from __future__ import annotations

import pytest

from app.domain.keywords import (
    match_keywords,
    match_keywords_in_profile,
    searchable_fields,
)
from app.domain.models import ExperienceItem, RawProfile


@pytest.mark.parametrize(
    ("keyword", "titles"),
    [
        ("vendor", "Vendor Manager"),                       # exact
        ("vendors", "Vendor Manager"),                      # plural in the query
        ("vendor", "Head of Vendors"),                      # plural in the profile
        ("vendor management", "Senior Vendor Manager"),     # manager ~ management
        ("procurement", "Procurement Specialist"),
        ("engineering", "Software Engineer"),               # engineer ~ engineering
        ("data analysis", "Data Analyst"),                  # analyst ~ analysis
        ("finance", "Financial Reporting Lead"),            # finance ~ financial
        ("VENDOR MANAGEMENT", "vendor manager"),            # case-insensitive
    ],
)
def test_terms_that_should_match(keyword, titles):
    assert match_keywords([keyword], titles).matched == [keyword]


@pytest.mark.parametrize(
    ("keyword", "titles"),
    [
        ("vendor management", "Marketing Manager"),   # only one token present
        ("kubernetes", "Vendor Manager"),             # absent entirely
        ("data", "Database Administrator"),           # 4-char prefix is below the floor
    ],
)
def test_terms_that_should_not_match(keyword, titles):
    result = match_keywords([keyword], titles)
    assert result.matched == []
    assert result.missing == [keyword]


def test_multi_word_keyword_needs_every_token():
    # "management" alone must not satisfy "vendor management".
    assert match_keywords(["vendor management"], "Operations Management").missing


def test_seniority_words_are_ignored_on_both_sides():
    # "Senior" carries no matching signal, so it neither helps nor blocks.
    assert match_keywords(["senior engineer"], "Staff Engineer").matched


def test_ratio_is_the_fraction_matched():
    result = match_keywords(["vendor", "kubernetes"], "Vendor Manager")
    assert result.ratio == pytest.approx(0.5)


def test_no_keywords_asked_for_scores_full_credit():
    # An unstated requirement must not penalise anyone.
    assert match_keywords([], "Vendor Manager").ratio == 1.0


def test_blank_entries_are_skipped():
    result = match_keywords(["vendor", "   ", ""], "Vendor Manager")
    assert result.matched == ["vendor"]
    assert result.missing == []


def test_original_spelling_is_preserved_for_display():
    result = match_keywords(["  Vendor Management  "], "vendor manager")
    assert result.matched == ["Vendor Management"]


def test_searchable_fields_cover_headline_current_and_past_titles():
    profile = RawProfile(
        source="mock",
        source_profile_url="https://example.com/in/x",
        name="X",
        headline="Operations Lead",
        current_title="Head of Operations",
        about="This about text must be ignored — vendor management lives here only.",
        experience=[ExperienceItem(title="Vendor Manager", company="Globex")],
    )
    text = " ".join(searchable_fields(profile))
    assert "Operations Lead" in text
    assert "Head of Operations" in text
    assert "Vendor Manager" in text
    # The About section is deliberately out of scope for keyword matching.
    assert "about text" not in text


def test_about_text_alone_does_not_satisfy_a_keyword():
    profile = RawProfile(
        source="mock",
        source_profile_url="https://example.com/in/x",
        name="X",
        headline="Operations Lead",
        about="I did a lot of vendor management at my last company.",
    )
    assert match_keywords_in_profile(["vendor management"], profile).missing


def test_credentials_are_searchable_wherever_the_candidate_recorded_them():
    """CPA counts whether it sits in the headline, the skills list, or certifications.

    The regression this guards: matching only titles made the result depend on
    a candidate's profile-keeping habits rather than on their qualifications.
    """
    base = dict(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name="X",
        current_title="External Audit Manager",
    )
    in_headline = RawProfile(**base, headline="External Audit Manager | CPA")
    in_skills = RawProfile(**base, headline="External Audit Manager", skills=["CPA", "IFRS"])
    in_certs = RawProfile(
        **base, headline="External Audit Manager", certifications=[{"name": "CPA"}]
    )
    in_licenses = RawProfile(
        **base, headline="External Audit Manager", licenses=[{"name": "CPA"}]
    )

    for profile in (in_headline, in_skills, in_certs, in_licenses):
        assert match_keywords_in_profile(["CPA"], profile).matched == ["CPA"]


def test_credential_entries_without_a_usable_name_are_skipped():
    profile = RawProfile(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name="X",
        headline="External Audit Manager",
        certifications=[{"issued": "2020"}, {"name": "CPA"}],
    )
    assert match_keywords_in_profile(["CPA"], profile).matched == ["CPA"]


def test_a_phrase_must_be_satisfied_inside_one_field():
    """"external audit manager" must not be assembled from separate fields.

    The regression: an Internal Audit Manager listing an unrelated "External
    Reporting" skill matched, because every field was flattened into one bag of
    words. External came from the skill, audit and manager from the title.
    """
    imposter = RawProfile(
        source="linkedin",
        source_profile_url="https://example.com/in/imposter",
        name="Imposter",
        headline="Internal Audit Manager",
        current_title="Internal Audit Manager",
        skills=["External Reporting", "IFRS"],
    )
    genuine = RawProfile(
        source="linkedin",
        source_profile_url="https://example.com/in/genuine",
        name="Genuine",
        headline="External Audit Manager",
        current_title="External Audit Manager",
    )

    assert match_keywords_in_profile(["external audit manager"], imposter).missing
    assert match_keywords_in_profile(["external audit manager"], genuine).matched


def test_single_word_keywords_still_match_any_field():
    # Only phrases are constrained to one field; a lone term may come from
    # anywhere the candidate declared it.
    profile = RawProfile(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name="X",
        headline="External Audit Manager",
        certifications=[{"name": "CPA"}],
    )
    result = match_keywords_in_profile(["external audit manager", "CPA"], profile)
    assert set(result.matched) == {"external audit manager", "CPA"}


def test_a_phrase_matches_a_past_role_even_if_the_current_one_differs():
    profile = RawProfile(
        source="linkedin",
        source_profile_url="https://example.com/in/x",
        name="X",
        headline="Finance Director",
        current_title="Finance Director",
        experience=[ExperienceItem(title="External Audit Manager", company="Firm")],
    )
    assert match_keywords_in_profile(["external audit manager"], profile).matched
