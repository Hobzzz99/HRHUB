"""LinkedIn provider — we drive a real browser ourselves.

⚠️  OPT-IN. Enabling this (`PROVIDER=linkedin`) scrapes LinkedIn with your own
account, which violates LinkedIn's User Agreement and risks the account being
restricted. Read COMPLIANCE.md. The mock provider runs the whole app without any
of this.

How this provider is meant to be used:

* **You sign in by hand.** The app never types credentials. A real window opens,
  you log in and clear any CAPTCHA yourself, and the resulting session is
  encrypted and reused so you rarely have to do it twice.
* **20 profiles an hour, enforced on disk.** See `providers/rate_limit.py`. This
  is the control that actually matters; the behavioural realism below only stops
  the *shape* of the traffic from being obviously synthetic.
* **Every interaction goes through `HumanActor`** — Bezier pointer paths with
  overshoot, inertial scroll bursts, log-normal pacing with micro-breaks, and a
  honeypot check before anything is clicked.

Implementation notes:
  * Extraction uses **Playwright locators only** (no BeautifulSoup) — the live
    DOM plus auto-waiting is enough, and avoids a redundant second parse.
  * One tab is reused for the whole run, the way a person browses, so pacing and
    pointer state stay continuous.
  * LinkedIn's DOM is obfuscated and changes often; the selectors below are
    best-effort with fallbacks and graceful degradation (missing fields become
    None/empty). They need real-world tuning against a live account — this
    provider is not covered by the automated test suite.
"""

from __future__ import annotations

import asyncio
import random
import re
import time
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
)
from playwright.async_api import (
    TimeoutError as PWTimeout,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.models import (
    EducationItem,
    ExperienceItem,
    RawProfile,
    SearchCriteria,
    SearchHit,
)
from app.providers.base import (
    CandidateProvider,
    ProfileUnavailableError,
    ProviderError,
    SessionCallback,
)
from app.providers.browser_pool import BrowserPool
from app.providers.human import HumanActor
from app.providers.human_motion import PacingProfile, lognormal_delay
from app.providers.rate_limit import LimiterSnapshot, SlidingWindowLimiter

logger = get_logger(__name__)

FEED_URL = "https://www.linkedin.com/feed/"
LOGIN_URL = "https://www.linkedin.com/login"

# Read from `document.scrollingElement` rather than `window.scrollY`/`body`:
# it is the element the browser actually scrolls, whichever that turns out to be.
_SCROLL_METRICS_JS = """() => {
  const el = document.scrollingElement || document.documentElement;
  return {
    top: Math.round(el.scrollTop),
    height: el.scrollHeight,
    inner: window.innerHeight,
    width: window.innerWidth,
    parts: document.querySelectorAll('[componentkey^="profileCardsBelowActivity"]').length,
  };
}"""

# Pages that mean "we are not logged in / are being challenged".
_BLOCKED_MARKERS = ("/authwall", "/checkpoint", "/uas/login", "/login")

# A security checkpoint specifically — a human can clear this one by hand, which
# is why it is distinguished from the other blocked pages above.
_CHALLENGE_MARKERS = ("/checkpoint/challenge", "/checkpoint/rm", "/checkpoint/lg")

# LinkedIn has restricted the account itself. Unlike a checkpoint this cannot be
# cleared by waiting or by any change to this code — the account cannot log in at
# all until its owner verifies their identity with LinkedIn directly.
_RESTRICTION_MARKERS = ("/login-restriction", "/checkpoint/lg/login-restriction")

# Signed-in chrome that is present on every authenticated page. Checked as well
# as the URL because LinkedIn serves the feed at several paths.
_AUTHED_MARKERS = ("#global-nav", "nav.global-nav", "[data-test-global-nav]")

# Exact `componentkey` suffixes per profile card. Exact, not "contains": a
# substring match on "Experience" would also catch VolunteerExperienceTopLevel.
_SECTION_KEYS: dict[str, tuple[str, ...]] = {
    "About": ("About",),
    "Experience": ("ExperienceTopLevelSection",),
    "Education": ("EducationTopLevelSection",),
    "Skills": ("Skills",),
}

# "Sep 2023 - Present", "Jan 2015 - Nov 2016". Requires a 4-digit year on the
# left so a bare tenure line ("9 yrs 9 mos") is not mistaken for a date range.
_DATE_RE = re.compile(
    r"\b\d{4}\b\s*[-–]\s*(?:present|[A-Za-z]{3,9}\.?\s+\d{4}|\d{4})", re.I
)
# Education shows plain years: "2007 – 2011".
_YEAR_RANGE_RE = re.compile(r"\b\d{4}\b\s*[-–]\s*(?:\b\d{4}\b|present)", re.I)

# Standalone employment-type lines sit between the job title and its dates.
_EMPLOYMENT_TYPES = frozenset(
    {
        "full-time", "part-time", "contract", "freelance", "internship",
        "self-employed", "seasonal", "apprenticeship", "temporary", "permanent",
    }
)

# Chrome that shares the Skills card's markup but is not a skill.
_SKILL_NOISE = frozenset({"Show all", "Skills", "Endorsements", "·", "Show less"})
# The second line of a skill entry: "1 endorsement", "12 endorsements".
_ENDORSEMENT_RE = re.compile(r"^\d+\s+endorsement", re.I)


class PlaywrightLinkedInProvider(CandidateProvider):
    name = "linkedin"

    def __init__(
        self,
        *,
        session_state: dict | None = None,
        on_session_update: SessionCallback | None = None,
        limiter: SlidingWindowLimiter | None = None,
        fingerprint_seed: str | None = None,
    ) -> None:
        self._session_state = session_state
        self._on_session_update = on_session_update
        # Pins the machine this account presents. Stable per account, distinct
        # between accounts — so a restriction on one does not link to the next
        # by way of identical hardware.
        self._fingerprint_seed = fingerprint_seed
        self._pool: BrowserPool | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._actor: HumanActor | None = None
        self._authenticated = False

        seed = settings.scrape_behavior_seed
        self._rng = random.Random(seed) if seed else random.Random()
        # The legacy delay bounds still steer the pacing: their midpoint becomes
        # the median of the log-normal gap between actions.
        midpoint_s = (settings.scrape_min_delay_ms + settings.scrape_max_delay_ms) / 2000.0
        self._pacing = PacingProfile(action_median_s=max(0.2, midpoint_s))
        self._limiter = limiter or default_limiter()

    # --- lifecycle ---------------------------------------------------------

    async def _get_context(self) -> BrowserContext:
        if self._context is None:
            # Own the browser for this search only (see browser_pool docstring:
            # a browser can't cross event loops / searches).
            if self._pool is None:
                self._pool = BrowserPool(fingerprint_seed=self._fingerprint_seed)
            self._context = await self._pool.new_context(storage_state=self._session_state)
        return self._context

    async def _get_page(self) -> tuple[Page, HumanActor]:
        """The single tab this run browses in, and its actor.

        Reusing one tab is both simpler and more human than opening a page per
        profile, and it keeps the actor's pointer position and micro-break
        counter continuous across the whole visit.
        """
        if self._page is None or self._page.is_closed():
            context = await self._get_context()
            self._page = await context.new_page()
            self._actor = HumanActor(self._page, rng=self._rng, profile=self._pacing)
            self._authenticated = False
        assert self._actor is not None
        return self._page, self._actor

    async def aclose(self) -> None:
        if self._context is not None:
            await self._persist_session(self._context)
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
        self._page = None
        self._actor = None
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _persist_session(self, context: BrowserContext) -> None:
        if self._on_session_update is None:
            return
        try:
            state = await context.storage_state()
            await self._on_session_update(state)
        except Exception:  # noqa: BLE001
            logger.warning("session_persist_failed", exc_info=True)

    def budget(self) -> LimiterSnapshot:
        """How much of the hourly profile budget is left. Safe to call anytime."""
        return self._limiter.snapshot()

    # --- auth --------------------------------------------------------------

    async def _ensure_authenticated(self, page: Page, actor: HumanActor) -> None:
        if self._authenticated and await self._is_authenticated(page):
            return
        await page.goto(FEED_URL, wait_until="domcontentloaded")
        await self._dismiss_cookie_banner(page, actor)
        # Let any client-side redirect settle before judging where we landed.
        await asyncio.sleep(lognormal_delay(1.2, self._rng))
        await self._raise_if_restricted(page)

        if await self._is_authenticated(page):
            logger.info("linkedin_session_reused")
            self._authenticated = True
            return

        await self._manual_sign_in(page, actor)

    async def _is_authenticated(self, page: Page) -> bool:
        """True when the page is signed-in chrome rather than a wall."""
        if self._is_blocked(page.url):
            return False
        if "/feed" in page.url:
            return True
        for marker in _AUTHED_MARKERS:
            try:
                if await page.locator(marker).count() > 0:
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    @staticmethod
    def _is_blocked(url: str) -> bool:
        return any(marker in url for marker in _BLOCKED_MARKERS)

    @staticmethod
    def _is_challenge(url: str) -> bool:
        return any(marker in url for marker in _CHALLENGE_MARKERS)

    @staticmethod
    def _is_restricted(url: str) -> bool:
        return any(marker in url for marker in _RESTRICTION_MARKERS)

    async def _raise_if_restricted(self, page: Page) -> None:
        """Fail loudly and accurately when LinkedIn has restricted the account.

        This is terminal: no retry, no waiting, and no change to this module can
        clear it. Reporting it as "no login form / likely a bot challenge" sends
        people looking for a selector bug that does not exist.
        """
        if not self._is_restricted(page.url):
            return
        shot = await self._dump_debug(page, "account-restricted")
        raise ProviderError(
            "LinkedIn has RESTRICTED this account — it is not a CAPTCHA and cannot "
            "be solved by retrying. LinkedIn detected the automated access and locked "
            "the account until its owner verifies their identity (government ID) at "
            "linkedin.com. Do not run this provider again on this account: further "
            "attempts risk making the restriction permanent. Switch the search to a "
            f"different data source. Debug: {shot}."
        )

    async def _manual_sign_in(self, page: Page, actor: HumanActor) -> None:
        """Open the login page and wait for the operator to sign in themselves."""
        if page.url.rstrip("/") != LOGIN_URL:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded")
            await self._dismiss_cookie_banner(page, actor)
        await self._wait_for_human(
            page,
            timeout_s=settings.scrape_login_timeout_s,
            label="sign-in",
            banner=(
                "Sign in to LinkedIn in the browser window that just opened "
                "(and clear any CAPTCHA / 2FA prompt)"
            ),
        )

    async def _wait_for_human(
        self, page: Page, *, timeout_s: int, label: str, banner: str
    ) -> None:
        """Hold the window open until the operator gets us to a signed-in page.

        This is the one waiting primitive for both first sign-in and a CAPTCHA
        that appears mid-run: in each case the exit condition is identical — the
        browser is on authenticated LinkedIn chrome again. Headless runs fail
        immediately, because nobody is there to do it.
        """
        if settings.scrape_headless:
            shot = await self._dump_debug(page, f"{label}-headless")
            raise ProviderError(
                f"LinkedIn needs a human ({label}) but this run is headless, so nobody "
                "can respond. Set SCRAPE_HEADLESS=false and run the search again — a "
                f"browser window will open and wait for you. Screenshot: {shot}."
            )

        logger.warning("linkedin_awaiting_human", label=label, timeout_s=timeout_s)
        print(f"\n>>> {banner}. Waiting up to {timeout_s}s...\n", flush=True)

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(2.0)
            if page.is_closed():
                raise ProviderError(
                    "The browser window was closed before sign-in finished. Run the "
                    "search again and leave the window open until it starts working."
                )
            # A restriction can land at any point in the wait and is terminal.
            await self._raise_if_restricted(page)
            if await self._is_authenticated(page):
                # Leaving a checkpoint is not the same as arriving on the feed:
                # LinkedIn usually bounces through an interstitial, so give it a
                # moment to land rather than judging the URL mid-flight.
                try:
                    await page.wait_for_url("**/feed/**", timeout=10000)
                except PWTimeout:
                    pass
                logger.info("linkedin_human_step_cleared", label=label, url=page.url)
                self._authenticated = True
                # A fresh sign-in mints a new session — keep it, so this is the
                # last time anyone has to do it.
                await self._persist_session(page.context)
                return

        shot = await self._dump_debug(page, f"{label}-timeout")
        raise ProviderError(
            f"LinkedIn {label} was not completed within {timeout_s}s. Run the search "
            "again and finish it in the browser window (raise SCRAPE_LOGIN_TIMEOUT_S "
            f"or SCRAPE_CHALLENGE_TIMEOUT_S if you need longer). Screenshot: {shot}."
        )

    async def _ensure_page_ok(self, page: Page, actor: HumanActor) -> None:
        """After a navigation: handle a restriction, a CAPTCHA, or a lost session."""
        await self._raise_if_restricted(page)
        if self._is_challenge(page.url):
            await self._wait_for_human(
                page,
                timeout_s=settings.scrape_challenge_timeout_s,
                label="security check",
                banner="LinkedIn is showing a security check — please solve it",
            )
            return
        if self._is_blocked(page.url):
            # The stored session expired mid-run. That is recoverable by hand,
            # so ask rather than failing the whole search.
            logger.warning("linkedin_session_lost", url=page.url)
            self._authenticated = False
            await self._manual_sign_in(page, actor)

    async def _dismiss_cookie_banner(self, page: Page, actor: HumanActor) -> None:
        for sel in (
            "button[action-type='ACCEPT']",
            "button:has-text('Accept')",
            "button:has-text('Agree')",
        ):
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    # Honeypot-checked like any other click; a hidden "accept"
                    # button is exactly the kind of bait worth not taking.
                    await actor.click(btn)
                    await asyncio.sleep(lognormal_delay(0.6, self._rng))
                    return
            except Exception:  # noqa: BLE001
                pass

    async def _dump_debug(self, page: Page, label: str) -> str:
        """Save a screenshot + HTML of whatever LinkedIn served, for diagnosis.

        The HTML is the half that matters: LinkedIn's markup is obfuscated and
        changes often, so the selectors in this module can only be tuned by
        reading the DOM the live site actually returned.
        """
        try:
            out = Path("_debug")
            out.mkdir(exist_ok=True)
            stamp = int(time.time())
            shot = out / f"{label}-{stamp}.png"
            await page.screenshot(path=str(shot), full_page=True)
            try:
                html = out / f"{label}-{stamp}.html"
                html.write_text(await page.content(), encoding="utf-8")
            except Exception:  # noqa: BLE001 — a screenshot alone still helps
                logger.warning("debug_html_dump_failed", exc_info=True)
            return str(shot.resolve())
        except Exception:  # noqa: BLE001
            return "n/a"

    # --- search ------------------------------------------------------------

    def _keywords(self, criteria: SearchCriteria) -> str:
        # LinkedIn filters location by a resolved geo facet (geoUrn), not free text.
        # Without its private typeahead API we can only fold location into the
        # keyword query — this biases results toward the location but does NOT
        # strictly filter to it. Proper geo filtering needs a structured provider.
        parts = [criteria.job_title, *criteria.keywords, criteria.location]
        return " ".join(p for p in parts if p and p.strip())

    async def search(self, criteria: SearchCriteria) -> list[SearchHit]:
        page, actor = await self._get_page()
        await self._ensure_authenticated(page, actor)
        keywords = self._keywords(criteria)

        hits: dict[str, SearchHit] = {}
        page_num = 1
        while len(hits) < criteria.max_results and page_num <= 10:
            if page_num == 1:
                await self._open_first_results_page(page, actor, keywords)
            else:
                await actor.settle()
                await page.goto(
                    self._results_url(keywords, page_num), wait_until="domcontentloaded"
                )
            await self._ensure_page_ok(page, actor)
            await actor.dwell(1.4)
            # Results hydrate lazily; reading down the page is what loads them.
            await actor.read_page(screens=2.5)

            found = await self._extract_hits(page)
            if not found:
                break
            for hit in found:
                hits.setdefault(hit.source_profile_url, hit)
            page_num += 1

        logger.info("linkedin_search_done", found=len(hits))
        return list(hits.values())[: criteria.max_results]

    @staticmethod
    def _results_url(keywords: str, page_num: int) -> str:
        return (
            "https://www.linkedin.com/search/results/people/"
            f"?keywords={quote_plus(keywords)}&page={page_num}"
        )

    async def _open_first_results_page(
        self, page: Page, actor: HumanActor, keywords: str
    ) -> None:
        """Run the first query through the real search box, typing it out.

        A session whose very first request is a deep `/search/results/people/`
        URL has no plausible history behind it. Typing into the global search
        box produces the navigation LinkedIn expects — and exercises the typing
        model (variable WPM, typo-and-backspace) on the one field this provider
        ever fills. Falls back to direct navigation, because a brittle nicety
        must never be what breaks a search.
        """
        if settings.scrape_humanize:
            try:
                await self._search_via_box(page, actor, keywords)
                return
            except Exception as exc:  # noqa: BLE001 — the fallback below always works
                # Deliberately no traceback: this path is expected to fail
                # whenever LinkedIn reshuffles its header, and a stack trace in
                # the log made a handled fallback look like a crash.
                logger.info("linkedin_search_box_unavailable", reason=str(exc)[:120])

        await actor.settle()
        await page.goto(self._results_url(keywords, 1), wait_until="domcontentloaded")

    async def _search_via_box(self, page: Page, actor: HumanActor, keywords: str) -> None:
        box = page.locator(
            "input.search-global-typeahead__input, "
            "#global-nav-search input[role='combobox'], "
            "input[placeholder='Search']"
        ).first
        await box.wait_for(state="visible", timeout=8000)

        await actor.settle()
        await actor.type_into(box, keywords)
        await asyncio.sleep(lognormal_delay(0.5, self._rng))
        await page.keyboard.press("Enter")
        await self._await_url(page, "/search/results/")
        await self._ensure_page_ok(page, actor)

        # The unfiltered "all" tab needs the People facet to become a people search.
        if "/search/results/people" not in page.url:
            people = page.locator(
                "button:has-text('People'), a[href*='/search/results/people']"
            ).first
            await people.wait_for(state="visible", timeout=8000)
            await actor.settle()
            await actor.click(people)
            await self._await_url(page, "/search/results/people")

    @staticmethod
    async def _await_url(page: Page, fragment: str, *, timeout_s: float = 20.0) -> None:
        """Wait for ``fragment`` to appear in the URL by polling it.

        ``page.wait_for_url`` waits for a *navigation* to reach the 'load'
        lifecycle. LinkedIn is a single-page app: switching to the People tab is
        a ``history.pushState`` with no document load, so the wait times out
        even though the URL is already correct — observed live, with Playwright
        itself logging that it had navigated to the very URL being waited for.
        Polling the URL asks the question that actually matters.
        """
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if fragment in page.url:
                return
            await asyncio.sleep(0.25)
        raise PWTimeout(f"URL never contained {fragment!r} (still {page.url})")

    async def _extract_hits(self, page: Page) -> list[SearchHit]:
        """Collect result cards, anchored to profile links (layout-resilient)."""
        hits: list[SearchHit] = []
        seen: set[str] = set()
        anchors = page.locator("a[href*='/in/']")
        for i in range(min(await anchors.count(), 40)):
            anchor = anchors.nth(i)
            href = await anchor.get_attribute("href")
            if not href:
                continue
            url = href.split("?")[0].rstrip("/")
            if "/in/" not in url or url in seen:
                continue
            seen.add(url)
            container = anchor.locator("xpath=ancestor::li[1]")
            hits.append(
                SearchHit(
                    source_profile_url=url,
                    name=await _text(anchor) or None,
                    headline=await _text(
                        container.locator(".entity-result__primary-subtitle")
                    ),
                    location=await _text(
                        container.locator(".entity-result__secondary-subtitle")
                    ),
                    current_company=None,
                )
            )
        return hits

    # --- profile -----------------------------------------------------------

    async def fetch_profile(self, hit: SearchHit) -> RawProfile:
        # Charged BEFORE the navigation, so a profile that fails to parse still
        # counts: LinkedIn saw the request either way. Raises RateLimitExceeded
        # when the budget is spent, which ends the run rather than this profile.
        waited = await self._limiter.acquire(
            max_wait_s=settings.scrape_rate_limit_max_wait_s
        )
        if waited:
            logger.info("linkedin_resumed_after_rate_limit", waited_s=round(waited, 1))

        page, actor = await self._get_page()
        await self._ensure_authenticated(page, actor)

        await actor.settle()
        await page.goto(hit.source_profile_url, wait_until="domcontentloaded")
        await self._ensure_page_ok(page, actor)

        # LinkedIn's authenticated profile DOM is obfuscated (no <h1>, no stable
        # classes, no JSON-LD). Wait for <main> to exist, then extract what we
        # reliably can — the name is always in the page <title>.
        try:
            await page.wait_for_selector("main", timeout=20000)
        except PWTimeout as exc:
            raise ProfileUnavailableError(
                f"Profile did not load: {hit.source_profile_url}"
            ) from exc

        await actor.dwell(1.5)
        # Reading the profile is what hydrates Experience and Skills, and is the
        # most human thing this provider does — recruiters read before moving on.
        await self._read_until_hydrated(page, actor)

        title = await page.title()
        name = title.split("|")[0].strip() or hit.name or "Unknown"
        card_headline, card_location = await self._top_card(page, name)
        headline = card_headline or hit.headline
        location = card_location or hit.location
        about = await self._extract_about(page)
        experience = await self._extract_experience(page)
        education = await self._extract_education(page)
        # Left until last: it may navigate away to the skills details page.
        skills = await self._extract_skills(page)

        # A profile that yields nothing but a name means every selector below
        # missed — the page loaded, so this is selector drift, not a bad URL.
        # Dump the DOM that beat them: it is the only way to retune them, and
        # silently storing an empty profile is what made every scraped
        # candidate score a meaningless flat 30.
        if not any((headline, about, experience, education, skills)):
            dump = await self._dump_debug(page, "profile-extraction-empty")
            logger.warning(
                "linkedin_profile_extraction_empty",
                url=hit.source_profile_url,
                debug=dump,
            )

        return RawProfile(
            source=self.name,
            source_profile_url=hit.source_profile_url,
            name=name,
            headline=headline or hit.headline,
            current_title=(experience[0].title if experience else None),
            current_company=(experience[0].company if experience else hit.current_company),
            location=location or hit.location,
            about=about,
            experience=experience,
            education=education,
            skills=skills,
        )

    @staticmethod
    async def section(page: Page, name: str) -> Locator:
        """A profile card, located the only two ways that survive a deploy.

        LinkedIn's profile is server-driven UI: every card carries a
        ``componentkey`` such as
        ``com.linkedin.sdui.profile.card.<urn>ExperienceTopLevelSection``, which
        is a server contract rather than a build artifact. Class names are
        content hashes (``_02257691``, ``d6f5ffc3``) that change on every
        release, so nothing here may depend on them.

        The key suffixes are exact on purpose: a ``*="Experience"`` match would
        also select the separate ``VolunteerExperienceTopLevel`` card.

        The heading-text fallback takes the **last** match, not the first. Every
        card is nested inside outer wrapper ``<section>`` elements, and
        ``:has()`` returns document order — so the first match is the wrapper
        holding the entire profile, which silently made "the Experience card"
        mean "everything" and mixed education and skills into the job history.
        The innermost match is the actual card.
        """
        for key in _SECTION_KEYS.get(name, (name,)):
            by_key = page.locator(f'section[componentkey$="{key}"]')
            if await by_key.count() >= 1:
                return by_key.first
        by_text = page.locator(f'section:has(h2:text-is("{name}"))')
        count = await by_text.count()
        return by_text.nth(count - 1) if count else by_text.first

    async def _read_until_hydrated(self, page: Page, actor: HumanActor) -> None:
        """Read down the profile until its lazy sections actually render.

        Experience, Education and Skills sit *below* the Activity feed and are
        only rendered once scrolled near. A fixed number of screenfuls stops
        short of them, so every extractor below then finds nothing and the
        profile is stored blank — which is exactly what happened on the first
        live run. Scroll like a reader until the sections appear, the page stops
        growing, or the budget runs out.
        """
        wanted = ("Experience", "Skills")
        stalled = 0
        for _ in range(settings.scrape_max_profile_scrolls):
            found = [w for w in wanted if await (await self.section(page, w)).count() > 0]
            if len(found) == len(wanted):
                logger.debug("linkedin_profile_hydrated", sections=found)
                return

            before = await page.evaluate(_SCROLL_METRICS_JS)
            await actor.scroll_by(int(before["inner"] * 0.85))
            await asyncio.sleep(lognormal_delay(1.2, self._rng))
            after = await page.evaluate(_SCROLL_METRICS_JS)

            moved = after["top"] != before["top"] or after["height"] != before["height"]
            at_bottom = after["top"] + after["inner"] >= after["height"] - 8
            stalled = 0 if moved else stalled + 1
            if not moved:
                # A wheel event goes to whatever is under the pointer; if that
                # is a non-scrolling region nothing happens. Re-centre and retry
                # before concluding the page has nothing left to give.
                await actor.move_to_point(
                    (after["width"] * 0.5, after["inner"] * 0.5), target_size=200.0
                )
            # Only give up at the genuine end of the content. A stall mid-page
            # just means one of the lazy card batches is still in flight, and
            # bailing there is what left every profile blank.
            if at_bottom and stalled >= 3:
                break

        # Reaching here means the loop ran out of road rather than returning
        # early. The sections may still have landed on the final pass, so only
        # say something when one is genuinely absent — a "sections_missing"
        # line listing nothing missing is just noise to page through later.
        missing = [w for w in wanted if await (await self.section(page, w)).count() == 0]
        if missing:
            logger.info("linkedin_profile_sections_missing", missing=missing, url=page.url)

    async def _top_card(self, page: Page, name: str) -> tuple[str | None, str | None]:
        """(headline, location) from the card at the top of the profile.

        The headline is simply the first paragraph under the name. The location
        is found by walking back from the "Contact info" link, which is a stable
        visible label — the lines around it (current company, school, the
        separator dot) shift about, so counting from the top does not hold.
        """
        heading = page.get_by_role("heading", name=name, exact=True).first
        if await heading.count() == 0:
            return None, None
        card = heading.locator("xpath=ancestor::section[1]")
        lines = [t.strip() for t in await card.locator("p").all_inner_texts() if t.strip()]
        if not lines:
            return None, None
        headline = lines[0]
        location = None
        if "Contact info" in lines:
            for candidate in reversed(lines[: lines.index("Contact info")]):
                # Skip the bare separator dot and the "Company · School" line.
                if candidate != "·" and " · " not in candidate:
                    location = candidate
                    break
        return headline, location

    async def _extract_about(self, page: Page) -> str | None:
        about = await self.section(page, "About")
        # LinkedIn wraps long text in an expandable box; that testid is the
        # most direct handle on the prose itself.
        text = await _text(about.locator('[data-testid="expandable-text-box"]').first)
        if text:
            return text
        text = await _text(about.locator("p").first)
        return text.removeprefix("About").strip() or None if text else None

    async def _extract_experience(self, page: Page) -> list[ExperienceItem]:
        """Roles from the Experience card, handling both of LinkedIn's layouts.

        An entry is a ``entity-collection-item`` component. It comes in two
        shapes: a single role, or one employer holding several roles as ``li``
        rows with the company named once in the group header. Reading the flat
        text cannot tell those apart — the line before a date range is the job
        title in one and the company in the other — so the container structure
        is what decides.
        """
        section = await self.section(page, "Experience")
        entries = section.locator('[componentkey^="entity-collection-item"]')
        items: list[ExperienceItem] = []
        for i in range(min(await entries.count(), 12)):
            entry = entries.nth(i)
            lines = [t.strip() for t in await entry.locator("p").all_inner_texts() if t.strip()]
            roles = entry.locator("li")
            role_count = await roles.count()

            if role_count > 1:
                # Grouped: the employer is named once, above the roles.
                company = lines[0] if lines else None
                for j in range(min(role_count, 10)):
                    role_lines = [
                        t.strip()
                        for t in await roles.nth(j).locator("p").all_inner_texts()
                        if t.strip()
                    ]
                    if (item := _role_from_lines(role_lines, company)) is not None:
                        items.append(item)
            elif (item := _role_from_lines(lines, None)) is not None:
                items.append(item)
        return items

    async def _extract_education(self, page: Page) -> list[EducationItem]:
        section = await self.section(page, "Education")
        entries = section.locator('[componentkey^="entity-collection-item"]')
        out: list[EducationItem] = []
        for i in range(min(await entries.count(), 8)):
            lines = [
                t.strip()
                for t in await entries.nth(i).locator("p").all_inner_texts()
                if t.strip()
            ]
            if not lines:
                continue
            dates = next((line for line in lines if _YEAR_RANGE_RE.search(line)), None)
            start, end = _split_dates(dates)
            degree = lines[1] if len(lines) > 1 and lines[1] != dates else None
            out.append(
                EducationItem(school=lines[0], degree=degree, start=start, end=end)
            )
        return out

    async def _extract_skills(self, page: Page) -> list[str]:
        """Skills, preferring the full list behind "Show all".

        The profile card shows only the top two of what is often dozens, and
        skills carry 30% of the match score — scoring a candidate on two of
        their seventy is worse than not scoring them at all. The details page is
        one extra request against a profile already being visited, so it does
        not consume another slot of the hourly budget.
        """
        inline = await self._card_skills(await self.section(page, "Skills"))
        if not settings.scrape_fetch_all_skills:
            return inline

        details = page.url.split("?")[0].rstrip("/") + "/details/skills/"
        try:
            await page.goto(details, wait_until="domcontentloaded")
            # Wait for the list itself, not just <main>. The page frame arrives
            # long before its entries do, and acting on the empty frame is what
            # made the fallback fire against the whole document.
            await page.locator('[componentkey^="entity-collection-item"]').first.wait_for(
                state="attached", timeout=15000
            )
            await self._read_until_hydrated_details(page)
            full = await self._collection_skills(page.locator("main"))
        except Exception:  # noqa: BLE001 — the inline list is a fine fallback
            logger.info("linkedin_skills_details_unavailable", url=details)
            return inline
        return full if len(full) > len(inline) else inline

    @staticmethod
    async def _collection_skills(scope: Locator) -> list[str]:
        """Skills from ``entity-collection-item`` entries, and nothing else.

        Each skill is one such item whose first paragraph is the name; a second
        line, when present, is an endorsement count. This is the only form
        allowed on the details page — see :meth:`_card_skills` for why there is
        no loose fallback here.
        """
        names: list[str] = []
        items = scope.locator('[componentkey^="entity-collection-item"]')
        for i in range(min(await items.count(), 150)):
            _add_skill(names, await _text(items.nth(i).locator("p").first))
        return names

    @classmethod
    async def _card_skills(cls, section: Locator) -> list[str]:
        """Top skills from the profile card, which may render them as bare ``<p>``.

        The paragraph sweep lives here and *only* here, because ``section`` is a
        single tightly-scoped card. Running the same sweep against the details
        page's ``<main>`` is what stored "Why am I seeing this ad?" and the
        names from the "People you may know" rail as this candidate's skills.
        """
        names = await cls._collection_skills(section)
        if names:
            return names
        for text in await section.locator("p").all_inner_texts():
            _add_skill(names, text)
        return names

    async def _read_until_hydrated_details(self, page: Page, passes: int = 20) -> None:
        """Scroll a details list until it stops producing new items.

        The list pages in as you scroll — a fixed number of wheel flicks
        returned the first ten of seventy-odd skills.
        """
        items = page.locator('[componentkey^="entity-collection-item"]')
        previous = -1
        for _ in range(passes):
            count = await items.count()
            metrics = await page.evaluate(_SCROLL_METRICS_JS)
            at_bottom = metrics["top"] + metrics["inner"] >= metrics["height"] - 8
            if at_bottom and count == previous:
                return
            previous = count
            await page.mouse.wheel(0, int(metrics["inner"] * 0.9))
            await asyncio.sleep(0.7)


def default_limiter() -> SlidingWindowLimiter:
    """The process-wide profile budget, configured from settings."""
    return SlidingWindowLimiter(
        limit=settings.scrape_max_profiles_per_hour,
        window_s=settings.scrape_rate_limit_window_s,
        state_path=Path(settings.scrape_state_dir) / "scrape_rate_limit.json",
        key="linkedin_profiles",
    )


# --- small helpers ---------------------------------------------------------


async def _text(locator: Locator) -> str | None:
    try:
        if await locator.count() == 0:
            return None
        value = (await locator.first.inner_text()).strip()
        return value or None
    except Exception:  # noqa: BLE001 — extraction is best-effort
        return None


def _add_skill(names: list[str], text: str | None) -> None:
    """Append ``text`` to ``names`` if it is plausibly a skill and not a repeat."""
    name = (text or "").strip()
    if (
        name
        and name not in names
        and 1 < len(name) < 60
        and name not in _SKILL_NOISE
        and not name.lower().startswith("show all")
        and not _ENDORSEMENT_RE.match(name)
        and not _DATE_RE.search(name)
    ):
        names.append(name)


def _role_from_lines(lines: list[str], group_company: str | None) -> ExperienceItem | None:
    """Build one role from an entry's text lines.

    Everything before the date range is the header; employment-type lines are
    dropped from it. What remains is the title, then (when the employer is not
    already known from a group header) the company — which LinkedIn sometimes
    writes as "Company · Full-time".
    """
    date_index = next((i for i, line in enumerate(lines) if _DATE_RE.search(line)), None)
    header = [
        line
        for line in (lines if date_index is None else lines[:date_index])
        if line.lower() not in _EMPLOYMENT_TYPES
    ]
    if not header:
        return None

    company = group_company
    if company is None and len(header) > 1:
        company = header[1].split("·")[0].strip() or None
    start, end = _split_dates(lines[date_index] if date_index is not None else None)
    return ExperienceItem(title=header[0], company=company, start=start, end=end)


def _split_dates(date_range: str | None) -> tuple[str | None, str | None]:
    """Split "Jan 2020 - Present · 4 yrs" into (start, end)."""
    if not date_range:
        return None, None
    core = date_range.split("·")[0].strip()
    for sep in (" - ", " – ", "–", "-"):
        if sep in core:
            start, end = core.split(sep, 1)
            return start.strip() or None, end.strip() or None
    return core or None, None
