"""Indeed candidate sourcing, driven through a real browser.

Mirrors the LinkedIn provider deliberately: manual sign-in, no stored
credentials, an hourly cap on profiles opened, the same human-behaviour and
fingerprint layers, and the same failure taxonomy. Only the site-specific parts
— URLs and extraction — differ, which is the whole point of the provider
interface.

**Indeed is not a second LinkedIn.** LinkedIn shows member profiles to any
signed-in member; Indeed's candidate database (Indeed Resume / Smart Sourcing)
sits behind an **employer** account and a paid subscription, and contacting a
candidate is metered separately. So this provider needs an employer login, not
a job-seeker one, and it is subject to Indeed's Terms of Service in the same way
the LinkedIn provider is subject to LinkedIn's. See COMPLIANCE.md.

**Selectors here have not been verified against a live employer session.** They
anchor on stable-looking attributes (`data-testid`, roles, visible text) rather
than generated class names, and every failure writes the page to `_debug/` so
the first real run can be turned into an accurate one. Treat the first search as
a calibration run.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from random import Random
from urllib.parse import quote_plus, urljoin

from playwright.async_api import BrowserContext, Locator, Page
from playwright.async_api import Error as PWError
from playwright.async_api import TimeoutError as PWTimeout

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
    AccountRestrictedError,
    CandidateProvider,
    ProfileUnavailableError,
    ProviderError,
    SessionCallback,
)
from app.providers.browser_pool import BrowserPool
from app.providers.human import HumanActor
from app.providers.human_motion import PacingProfile, lognormal_delay
from app.providers.rate_limit import LimiterSnapshot, SlidingWindowLimiter, budget_for

logger = get_logger(__name__)

BASE_URL = "https://resumes.indeed.com"
SIGNED_IN_URL = f"{BASE_URL}/search"
LOGIN_URL = "https://secure.indeed.com/auth"

#: URL fragments that mean the session is not usable.
_LOGIN_MARKERS = ("/auth", "/account/login", "secure.indeed.com")
#: Indeed fronts its employer product with Cloudflare; a challenge page is a
#: human problem, not a selector problem, and must say so.
_CHALLENGE_MARKERS = ("/challenge", "cf-challenge", "captcha")
#: Suspension or a subscription that has lapsed. Terminal for this account.
_BLOCKED_MARKERS = ("/account-suspended", "/subscription-required", "/plan-required")

#: Signed-in chrome present on every employer page.
_AUTHED_MARKERS = (
    '[data-testid="resume-search-results"]',
    '[data-testid="employer-nav"]',
    'nav[aria-label*="Employer" i]',
)

#: One result card in the resume search list.
_RESULT_CARD = (
    '[data-testid="resume-search-result"]',
    '[data-testid="ResumeCard"]',
    'article:has(a[href*="/resume/"])',
    'li:has(a[href*="/resume/"])',
)


class IndeedProvider(CandidateProvider):
    """Employer-side Indeed resume search."""

    name = "indeed"

    def __init__(
        self,
        *,
        session_state: dict | None = None,
        on_session_update: SessionCallback | None = None,
        fingerprint_seed: str | None = None,
        limiter: SlidingWindowLimiter | None = None,
    ) -> None:
        self._session_state = session_state
        self._on_session_update = on_session_update
        self._pool: BrowserPool | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._actor: HumanActor | None = None
        self._authenticated = False
        self._fingerprint_seed = fingerprint_seed
        self._limiter = limiter or budget_for("indeed")

        seed = settings.scrape_behavior_seed
        self._rng = Random(seed) if seed else Random()
        midpoint_s = (settings.scrape_min_delay_ms + settings.scrape_max_delay_ms) / 2000.0
        self._pacing = PacingProfile(action_median_s=max(0.2, midpoint_s))

    # --- lifecycle ---------------------------------------------------------

    async def _get_context(self) -> BrowserContext:
        if self._context is None:
            self._pool = BrowserPool(fingerprint_seed=self._fingerprint_seed)
            await self._pool.start()
            self._context = await self._pool.new_context(self._session_state)
        return self._context

    async def _get_page(self) -> tuple[Page, HumanActor]:
        context = await self._get_context()
        if self._page is None or self._page.is_closed():
            self._page = await context.new_page()
            self._actor = HumanActor(self._page, rng=self._rng, profile=self._pacing)
            self._authenticated = False
        assert self._actor is not None
        return self._page, self._actor

    async def aclose(self) -> None:
        if self._context is not None:
            # Only after a successful sign-in — see the LinkedIn provider for
            # what saving a logged-out session over a good one costs.
            if self._authenticated:
                await self._persist_session(self._context)
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001 — best-effort teardown
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
        except Exception:  # noqa: BLE001 — a lost session costs one extra login
            logger.warning("indeed_session_persist_failed", exc_info=True)

    def budget(self) -> LimiterSnapshot:
        """How much of the hourly profile budget is left. Safe to call anytime."""
        return self._limiter.snapshot()

    # --- navigation --------------------------------------------------------

    async def _goto(self, page: Page, url: str) -> None:
        """Navigate, translating the failure modes of someone else's site."""
        try:
            await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=settings.scrape_navigation_timeout_s * 1000,
            )
        except PWTimeout as exc:
            raise ProfileUnavailableError(
                f"Timed out after {settings.scrape_navigation_timeout_s}s loading {url}."
            ) from exc
        except PWError as exc:
            raise ProfileUnavailableError(f"Could not load {url}: {exc}") from exc

    @staticmethod
    def _is_login(url: str) -> bool:
        return any(marker in url for marker in _LOGIN_MARKERS)

    @staticmethod
    def _is_challenge(url: str) -> bool:
        return any(marker in url for marker in _CHALLENGE_MARKERS)

    @staticmethod
    def _is_blocked(url: str) -> bool:
        return any(marker in url for marker in _BLOCKED_MARKERS)

    async def _raise_if_blocked(self, page: Page) -> None:
        """Fail loudly when the employer account cannot be used at all.

        Terminal, like a LinkedIn restriction: neither a retry nor a code change
        clears a suspended account or a lapsed subscription, and reporting it as
        a generic scrape failure sends someone hunting a selector bug.
        """
        if not self._is_blocked(page.url):
            return
        shot = await self._dump_debug(page, "indeed-blocked")
        raise AccountRestrictedError(
            "Indeed will not serve resume search for this account — it is "
            "suspended, or the employer subscription that Indeed Resume requires "
            "is not active. This is not something the app can retry. Check the "
            f"account at employers.indeed.com. Debug: {shot}."
        )

    async def _is_authenticated(self, page: Page) -> bool:
        if self._is_login(page.url):
            return False
        for marker in _AUTHED_MARKERS:
            try:
                if await page.locator(marker).count() > 0:
                    return True
            except Exception:  # noqa: BLE001 — one unusable marker is not a verdict
                pass
        return False

    async def _ensure_authenticated(self, page: Page, actor: HumanActor) -> None:
        if self._authenticated and await self._is_authenticated(page):
            return
        await self._goto(page, SIGNED_IN_URL)
        await asyncio.sleep(lognormal_delay(1.2, self._rng))
        await self._raise_if_blocked(page)

        if await self._is_authenticated(page):
            logger.info("indeed_session_reused")
            self._authenticated = True
            return

        await self._wait_for_human(
            page,
            timeout_s=settings.scrape_login_timeout_s,
            banner=(
                "Sign in to Indeed as an EMPLOYER in the browser window that just "
                "opened (a job-seeker account cannot search resumes)"
            ),
        )

    async def _wait_for_human(self, page: Page, *, timeout_s: int, banner: str) -> None:
        """Hold the window open until the operator gets us to a signed-in page."""
        logger.warning("indeed_waiting_for_human", action=banner, timeout_s=timeout_s)
        deadline = asyncio.get_running_loop().time() + timeout_s
        while asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(2.0)
            if page.is_closed():
                raise ProviderError("The browser window was closed before sign-in.")
            await self._raise_if_blocked(page)
            if await self._is_authenticated(page):
                logger.info("indeed_signed_in")
                self._authenticated = True
                await self._persist_session(await self._get_context())
                return
        raise ProviderError(
            f"Nobody signed in to Indeed within {timeout_s}s. Set "
            "SCRAPE_LOGIN_TIMEOUT_S higher, or sign in before starting a search."
        )

    async def _dump_debug(self, page: Page, label: str) -> str:
        """Save a screenshot + HTML of whatever Indeed served, for diagnosis.

        The HTML is the half that matters. The selectors in this module were
        written without a live employer session to read, so the first real run
        is what turns them from plausible into correct.
        """
        try:
            out = Path("_debug")
            out.mkdir(exist_ok=True)
            stamp = int(time.time())
            shot = out / f"{label}-{stamp}.png"
            await page.screenshot(path=str(shot), full_page=True)
            try:
                (out / f"{label}-{stamp}.html").write_text(
                    await page.content(), encoding="utf-8"
                )
            except Exception:  # noqa: BLE001 — a screenshot alone still helps
                logger.warning("indeed_debug_html_failed", exc_info=True)
            return str(shot.resolve())
        except Exception:  # noqa: BLE001 — diagnostics must never break a search
            return "n/a"

    # --- search ------------------------------------------------------------

    def _query(self, criteria: SearchCriteria) -> str:
        parts = [criteria.job_title, *criteria.keywords]
        return " ".join(p for p in parts if p and p.strip())

    @staticmethod
    def _search_url(query: str, location: str | None, page_num: int) -> str:
        url = f"{BASE_URL}/search?q={quote_plus(query)}"
        if location and location.strip():
            url += f"&l={quote_plus(location.strip())}"
        if page_num > 1:
            # Indeed pages resumes in blocks of 50 by offset, not page number.
            url += f"&start={(page_num - 1) * 50}"
        return url

    async def search(self, criteria: SearchCriteria) -> list[SearchHit]:
        page, actor = await self._get_page()
        await self._ensure_authenticated(page, actor)
        query = self._query(criteria)

        hits: dict[str, SearchHit] = {}
        page_num = 1
        while len(hits) < criteria.max_results and page_num <= 10:
            await actor.settle()
            await self._goto(page, self._search_url(query, criteria.location, page_num))
            await self._raise_if_blocked(page)
            if self._is_challenge(page.url):
                await self._dump_debug(page, "indeed-challenge")
                raise ProviderError(
                    "Indeed served a bot challenge. Clear it in the open browser "
                    "window, then re-run the search."
                )
            await actor.dwell(1.4)
            await actor.read_page(screens=2.5)

            found = await self._extract_hits(page)
            if not found:
                break
            for hit in found:
                hits.setdefault(hit.source_profile_url, hit)
            page_num += 1

        logger.info("indeed_search_done", found=len(hits))
        return list(hits.values())[: criteria.max_results]

    async def _extract_hits(self, page: Page) -> list[SearchHit]:
        cards: list[Locator] = []
        for selector in _RESULT_CARD:
            located = page.locator(selector)
            if await located.count() > 0:
                cards = [located.nth(i) for i in range(await located.count())]
                break
        if not cards:
            await self._dump_debug(page, "indeed-no-results")
            return []

        hits: list[SearchHit] = []
        for card in cards:
            link = card.locator('a[href*="/resume/"]').first
            href = await _attr(link, "href")
            if not href:
                continue
            hits.append(
                SearchHit(
                    source_profile_url=urljoin(BASE_URL, href.split("?")[0]),
                    name=await _text(card.locator('[data-testid="resume-name"], h2, h3')),
                    headline=await _text(
                        card.locator('[data-testid="resume-headline"], h3 + div, p')
                    ),
                    current_company=await _text(
                        card.locator('[data-testid="resume-company"]')
                    ),
                    location=await _text(card.locator('[data-testid="resume-location"]')),
                )
            )
        return hits

    # --- profile -----------------------------------------------------------

    async def fetch_profile(self, hit: SearchHit) -> RawProfile:
        # Charged against the hourly budget *before* the page is opened, so a
        # spent budget costs nothing rather than one profile too many.
        await self._limiter.acquire(max_wait_s=settings.scrape_rate_limit_max_wait_s)

        page, actor = await self._get_page()
        await self._ensure_authenticated(page, actor)
        await actor.settle()
        await self._goto(page, hit.source_profile_url)
        await self._raise_if_blocked(page)
        await actor.dwell(1.2)
        await actor.read_page(screens=3.0)

        name = await _text(page.locator('[data-testid="resume-name"], h1')) or hit.name
        if not name:
            shot = await self._dump_debug(page, "indeed-profile-empty")
            raise ProfileUnavailableError(
                f"No name found on {hit.source_profile_url}. Debug: {shot}."
            )

        experience = await self._extract_experience(page)
        return RawProfile(
            source=self.name,
            source_profile_url=hit.source_profile_url,
            name=name,
            headline=await _text(page.locator('[data-testid="resume-headline"]'))
            or hit.headline,
            current_title=experience[0].title if experience else None,
            current_company=experience[0].company if experience else hit.current_company,
            location=await _text(page.locator('[data-testid="resume-location"]'))
            or hit.location,
            about=await _text(page.locator('[data-testid="resume-summary"]')),
            experience=experience,
            education=await self._extract_education(page),
            skills=await self._extract_skills(page),
        )

    async def _extract_experience(self, page: Page) -> list[ExperienceItem]:
        section = page.locator('[data-testid="resume-work-experience"] li, '
                               'section:has(h2:text-is("Work Experience")) li')
        items: list[ExperienceItem] = []
        for i in range(min(await section.count(), 30)):
            entry = section.nth(i)
            title = await _text(entry.locator('[data-testid="workExperience-title"], h3'))
            if not title:
                continue
            dates = await _text(entry.locator('[data-testid="workExperience-dates"]'))
            start, end = _split_dates(dates)
            items.append(
                ExperienceItem(
                    title=title,
                    company=await _text(
                        entry.locator('[data-testid="workExperience-company"]')
                    ),
                    start=start,
                    end=end,
                )
            )
        return items

    async def _extract_education(self, page: Page) -> list[EducationItem]:
        section = page.locator('[data-testid="resume-education"] li, '
                               'section:has(h2:text-is("Education")) li')
        items: list[EducationItem] = []
        for i in range(min(await section.count(), 20)):
            entry = section.nth(i)
            school = await _text(entry.locator('[data-testid="education-school"], h3'))
            degree = await _text(entry.locator('[data-testid="education-degree"]'))
            if not (school or degree):
                continue
            dates = await _text(entry.locator('[data-testid="education-dates"]'))
            start, end = _split_dates(dates)
            items.append(
                EducationItem(school=school, degree=degree, start=start, end=end)
            )
        return items

    async def _extract_skills(self, page: Page) -> list[str]:
        located = page.locator('[data-testid="resume-skill"], '
                               'section:has(h2:text-is("Skills")) li')
        names: list[str] = []
        for i in range(min(await located.count(), 100)):
            value = (await _text(located.nth(i)) or "").strip()
            if value and value not in names and 1 < len(value) < 60:
                names.append(value)
        return names


# --- small helpers ---------------------------------------------------------


async def _text(locator: Locator) -> str | None:
    try:
        if await locator.count() == 0:
            return None
        value = (await locator.first.inner_text()).strip()
        return value or None
    except Exception:  # noqa: BLE001 — extraction is best-effort
        return None


async def _attr(locator: Locator, name: str) -> str | None:
    try:
        if await locator.count() == 0:
            return None
        return await locator.first.get_attribute(name)
    except Exception:  # noqa: BLE001 — extraction is best-effort
        return None


def _split_dates(date_range: str | None) -> tuple[str | None, str | None]:
    """Split "January 2020 to Present" into (start, end)."""
    if not date_range:
        return None, None
    core = date_range.strip()
    for sep in (" to ", " - ", " – ", "–", "-"):
        if sep in core:
            start, end = core.split(sep, 1)
            return start.strip() or None, end.strip() or None
    return core or None, None
