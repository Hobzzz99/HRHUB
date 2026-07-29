"""Extraction tests against LinkedIn's current profile markup.

The fixture below is **synthetic**, but its structure is copied exactly from a
real logged-in profile captured on 2026-07-29: hashed class names, server-driven
`componentkey` attributes, and the two different shapes an Experience entry
takes. No real person's data is stored here — warehousing a scraped profile in
the repo would contradict the data-minimization rule in COMPLIANCE.md.

These pin the parsing rules that were wrong on the first live run:
  * sections resolved to an outer wrapper, so "Experience" meant "the whole page"
  * grouped roles lost their employer
  * a standalone entry's company was read as its job title
"""

from __future__ import annotations

import pytest
from playwright.async_api import async_playwright

from app.core.config import settings
from app.providers.playwright_linkedin import PlaywrightLinkedInProvider

URN = "com.linkedin.sdui.profile.card.refXYZ"

# Wrapper <section>s deliberately nest the cards: the real page does this, and
# it is what made a "first match" section lookup select the entire profile.
PROFILE_HTML = f"""
<!doctype html><html><body><section class="_02257691"><section class="a6cd1836">

  <section class="b962cef7" componentkey="{URN}TopCard">
    <h2 class="_7ae5b473">Dana Okonkwo</h2>
    <p class="ab88715b">Head of Finance at Northwind Hotels</p>
    <p class="ab88715b">Northwind Hotels &middot; Riverside University</p>
    <p class="ab88715b">Lagos, Nigeria</p>
    <p class="ab88715b">&middot;</p>
    <p class="ab88715b">Contact info</p>
    <p class="ab88715b">500+</p>
  </section>

  <section class="b962cef7" componentkey="{URN}About">
    <h2 class="_7ae5b473">About</h2>
    <p><span data-testid="expandable-text-box">Finance leader in hospitality.</span></p>
  </section>

  <section class="b962cef7" componentkey="{URN}ExperienceTopLevelSection">
    <h2 class="_7ae5b473">Experience</h2>

    <div componentkey="entity-collection-item--aaa">
      <p>Northwind Hotels</p>
      <p>7 yrs 2 mos</p>
      <ul>
        <li>
          <p>Head of Finance</p>
          <p>Full-time</p>
          <p>Sep 2023 - Present &middot; 2 yrs 11 mos</p>
          <p>Lagos, Nigeria &middot; On-site</p>
          <p>Budgeting, Forecasting and +3 skills</p>
        </li>
        <li>
          <p>Financial Controller</p>
          <p>Full-time</p>
          <p>Jul 2019 - Sep 2023 &middot; 4 yrs 3 mos</p>
          <p>Lagos, Nigeria</p>
        </li>
      </ul>
    </div>

    <div componentkey="entity-collection-item--bbb">
      <p>Senior Accountant</p>
      <p>Harbour Group</p>
      <p>Jan 2016 - Jul 2019 &middot; 3 yrs 7 mos</p>
      <p>Abuja</p>
    </div>

    <div componentkey="entity-collection-item--ccc">
      <p>Audit Associate</p>
      <p>Meridian Bank &middot; Full-time</p>
      <p>Mar 2014 - Jan 2016 &middot; 1 yr 11 mos</p>
    </div>
  </section>

  <section class="b962cef7" componentkey="{URN}VolunteerExperienceTopLevel">
    <h2 class="_7ae5b473">Volunteer Experience</h2>
    <div componentkey="entity-collection-item--vvv">
      <p>Treasurer</p>
      <p>Community Trust</p>
      <p>Jan 2020 - Present &middot; 6 yrs</p>
    </div>
  </section>

  <section class="b962cef7" componentkey="{URN}EducationTopLevelSection">
    <h2 class="_7ae5b473">Education</h2>
    <div componentkey="entity-collection-item--edu">
      <p>Riverside University</p>
      <p>Bachelor of Commerce, Accounting</p>
      <p>2007 &ndash; 2011</p>
    </div>
  </section>

  <section class="b962cef7" componentkey="{URN}Skills">
    <h2 class="_7ae5b473">Skills (74)</h2>
    <p>Financial Reporting</p>
    <p>Internal Audit</p>
    <p>Show all</p>
  </section>

</section></section></body></html>
"""


@pytest.fixture
async def page():
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        pg = await (await browser.new_context()).new_page()
        await pg.set_content(PROFILE_HTML)
        yield pg
        await browser.close()


@pytest.fixture
def provider(monkeypatch):
    # The skills details page does not exist in a fixture; exercise inline only.
    monkeypatch.setattr(settings, "scrape_fetch_all_skills", False)
    return PlaywrightLinkedInProvider()


async def test_sections_resolve_to_the_card_not_an_outer_wrapper(provider, page):
    # The cards are nested inside two wrapper <section>s. Document order returns
    # the wrapper first, so a `.first` lookup silently selected the whole page.
    for name in ("About", "Experience", "Education", "Skills"):
        section = await provider.section(page, name)
        assert await section.count() == 1
        assert await section.locator("h2").first.inner_text() != "Dana Okonkwo"


async def test_experience_card_excludes_volunteer_experience(provider, page):
    # A `*="Experience"` key match would also select VolunteerExperienceTopLevel.
    section = await provider.section(page, "Experience")
    text = await section.inner_text()
    assert "Treasurer" not in text


async def test_top_card_reads_headline_and_location(provider, page):
    headline, location = await provider._top_card(page, "Dana Okonkwo")
    assert headline == "Head of Finance at Northwind Hotels"
    # Location is found by walking back from "Contact info"; counting forward
    # would land on the "Company · School" line.
    assert location == "Lagos, Nigeria"


async def test_top_card_survives_an_unknown_name(provider, page):
    assert await provider._top_card(page, "Nobody At All") == (None, None)


async def test_about_comes_from_the_expandable_box(provider, page):
    assert await provider._extract_about(page) == "Finance leader in hospitality."


async def test_every_role_is_found_across_both_entry_shapes(provider, page):
    roles = await provider._extract_experience(page)
    assert [r.title for r in roles] == [
        "Head of Finance",
        "Financial Controller",
        "Senior Accountant",
        "Audit Associate",
    ]


async def test_grouped_roles_inherit_the_employer(provider, page):
    roles = await provider._extract_experience(page)
    # These two are `li` rows under one employer named once in the group header.
    assert roles[0].company == "Northwind Hotels"
    assert roles[1].company == "Northwind Hotels"


async def test_standalone_entry_separates_title_from_company(provider, page):
    roles = await provider._extract_experience(page)
    assert (roles[2].title, roles[2].company) == ("Senior Accountant", "Harbour Group")


async def test_company_is_split_from_its_employment_type(provider, page):
    roles = await provider._extract_experience(page)
    assert roles[3].company == "Meridian Bank"


async def test_employment_type_is_never_mistaken_for_a_title(provider, page):
    roles = await provider._extract_experience(page)
    assert not any(r.title.lower() == "full-time" for r in roles)


async def test_dates_are_parsed_including_an_open_ended_role(provider, page):
    roles = await provider._extract_experience(page)
    assert (roles[0].start, roles[0].end) == ("Sep 2023", "Present")
    assert (roles[2].start, roles[2].end) == ("Jan 2016", "Jul 2019")


async def test_tenure_line_is_not_read_as_a_date_range(provider, page):
    # "7 yrs 2 mos" sits directly above the first role and has no year in it.
    roles = await provider._extract_experience(page)
    assert all(r.start is None or "yr" not in r.start for r in roles)


async def test_education_is_extracted(provider, page):
    education = await provider._extract_education(page)
    assert len(education) == 1
    assert education[0].school == "Riverside University"
    assert education[0].degree == "Bachelor of Commerce, Accounting"
    assert (education[0].start, education[0].end) == ("2007", "2011")


async def test_skills_are_extracted_without_chrome(provider, page):
    skills = await provider._extract_skills(page)
    assert "Financial Reporting" in skills
    assert "Internal Audit" in skills
    assert not any("show all" in s.lower() for s in skills)


# The skills *details* page renders each skill as an entity-collection-item and
# sits on a page that also carries ad controls and a "People you may know" rail.
# Scoping to `main` swept those in and stored them as skills.
SKILLS_DETAILS_HTML = """
<!doctype html><html><body><main>
  <div componentkey="entity-collection-item--s1"><p>Financial Reporting</p></div>
  <div componentkey="entity-collection-item--s2">
    <p>Internal Audit</p><p>12 endorsements</p>
  </div>
  <div componentkey="entity-collection-item--s3"><p>Budgeting</p><p>1 endorsement</p></div>
  <aside>
    <p>Why am I seeing this ad?</p>
    <p>Manage your ad preferences</p>
    <p>Moataz Nour</p>
    <p>· 3rd+</p>
    <p>Director of Human Resources</p>
  </aside>
</main></body></html>
"""


async def test_details_list_yields_skills_not_page_chrome(provider):
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        pg = await (await browser.new_context()).new_page()
        await pg.set_content(SKILLS_DETAILS_HTML)

        skills = await provider._collection_skills(pg.locator("main"))

        assert skills == ["Financial Reporting", "Internal Audit", "Budgeting"]
        # The specific junk that reached the database on the first working run.
        assert not any("ad" in s.lower() and "?" in s for s in skills)
        assert "Moataz Nour" not in skills
        assert "· 3rd+" not in skills
        # Endorsement counts are metadata about a skill, not a skill.
        assert not any("endorsement" in s.lower() for s in skills)
        await browser.close()


async def test_empty_details_list_yields_nothing_rather_than_the_page(provider):
    """An unhydrated details page must produce no skills, not every paragraph.

    This is the exact failure that reached the database: the list had not
    rendered yet, so a paragraph sweep over <main> returned 38 "skills" made of
    ad controls and sidebar names — and 38 > 2 beat the real inline list.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        pg = await (await browser.new_context()).new_page()
        await pg.set_content(
            "<main><aside><p>Why am I seeing this ad?</p>"
            "<p>Moataz Nour</p><p>· 3rd+</p></aside></main>"
        )
        assert await provider._collection_skills(pg.locator("main")) == []
        await browser.close()
