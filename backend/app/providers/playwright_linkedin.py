"""LinkedIn provider via Playwright.

⚠️  OPT-IN AND OFF BY DEFAULT. Enabling this (`PROVIDER=playwright`) automates a
LinkedIn login and scrapes profiles, which violates LinkedIn's User Agreement and
risks account bans and legal exposure. Read COMPLIANCE.md. The mock provider runs
the whole app without any of this.

Implementation notes:
  * Extraction uses **Playwright locators only** (no BeautifulSoup) — the live DOM
    plus auto-waiting is enough, and avoids a redundant second parse.
  * Sessions are restored from encrypted `storage_state` so logins are rare; a new
    session, once established, is handed back via `on_session_update` to persist.
  * Human-like delays with jitter are inserted between actions.
  * LinkedIn's DOM is obfuscated and changes often; the selectors below are
    best-effort with fallbacks and graceful degradation (missing fields become
    None/empty). They will need real-world tuning against a live account — this
    provider is not covered by the automated test suite.
"""

from __future__ import annotations

import asyncio
import random
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from urllib.parse import quote_plus

from playwright.async_api import (
    BrowserContext,
    Locator,
    Page,
    TimeoutError as PWTimeout,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.domain.models import ExperienceItem, RawProfile, SearchCriteria, SearchHit
from app.providers.base import CandidateProvider, ProfileUnavailableError, ProviderError
from app.providers.browser_pool import BrowserPool

logger = get_logger(__name__)

SessionCallback = Callable[[dict], Awaitable[None]]

# Pages that mean "we are not logged in / are being challenged".
_BLOCKED_MARKERS = ("/authwall", "/checkpoint", "/uas/login", "/login")

# A security checkpoint specifically — a human can clear this one by hand, which
# is why it is distinguished from the other blocked pages above.
_CHALLENGE_MARKERS = ("/checkpoint/challenge", "/checkpoint/rm", "/checkpoint/lg")

# LinkedIn has restricted the account itself. Unlike a checkpoint this cannot be
# cleared by waiting or by any change to this code — the account cannot log in at
# all until its owner verifies their identity with LinkedIn directly.
_RESTRICTION_MARKERS = ("/login-restriction", "/checkpoint/lg/login-restriction")


class PlaywrightLinkedInProvider(CandidateProvider):
    name = "linkedin"

    def __init__(
        self,
        *,
        credentials: dict | None = None,
        session_state: dict | None = None,
        on_session_update: SessionCallback | None = None,
    ) -> None:
        self._credentials = credentials or {}
        self._session_state = session_state
        self._on_session_update = on_session_update
        self._pool: BrowserPool | None = None
        self._context: BrowserContext | None = None

    # --- lifecycle ---------------------------------------------------------

    async def _get_context(self) -> BrowserContext:
        if self._context is None:
            # Own the browser for this search only (see browser_pool docstring:
            # a browser can't cross event loops / searches).
            if self._pool is None:
                self._pool = BrowserPool()
            self._context = await self._pool.new_context(storage_state=self._session_state)
        return self._context

    async def aclose(self) -> None:
        if self._context is not None:
            await self._persist_session(self._context)
            try:
                await self._context.close()
            except Exception:  # noqa: BLE001
                pass
            self._context = None
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

    async def _human_delay(self) -> None:
        lo, hi = settings.scrape_min_delay_ms, settings.scrape_max_delay_ms
        await asyncio.sleep(random.uniform(lo, hi) / 1000.0)

    # --- auth --------------------------------------------------------------

    async def _ensure_authenticated(self, page: Page) -> None:
        await page.goto("https://www.linkedin.com/feed/", wait_until="domcontentloaded")
        await self._dismiss_cookie_banner(page)
        await asyncio.sleep(1.0)  # let any client-side redirect settle
        await self._raise_if_restricted(page)
        # A checkpoint on the way to the feed can often be cleared by hand.
        if self._is_challenge(page.url):
            await self._await_human_challenge(page)
        # If we're on the feed (and not bounced to a login/authwall), the persisted
        # session is valid — don't attempt a fresh login.
        if "/feed" in page.url and not self._is_blocked(page.url):
            logger.info("linkedin_session_reused")
            return
        await self._login(page)

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

    async def _await_human_challenge(self, page: Page) -> None:
        """Hold the browser open on a checkpoint so a human can clear it.

        LinkedIn's checkpoint is a human-verification challenge; the only sanctioned
        way past it is a person solving it. Headed runs therefore park here and poll
        until the page leaves the checkpoint. Headless runs fail fast — nobody is
        watching the window, so waiting would just burn the timeout.
        """
        if settings.scrape_headless:
            shot = await self._dump_debug(page, "challenge-headless")
            raise ProviderError(
                "LinkedIn is showing a security checkpoint and this run is headless, "
                "so nobody can solve it. Set SCRAPE_HEADLESS=false and run the search "
                f"again — a browser window will open and wait for you. Screenshot: {shot}."
            )

        timeout_s = settings.scrape_challenge_timeout_s
        logger.warning("linkedin_challenge_awaiting_human", timeout_s=timeout_s)
        print(
            f"\n>>> LinkedIn is showing a security check. Solve it in the browser "
            f"window that just opened — waiting up to {timeout_s}s...\n",
            flush=True,
        )
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            await asyncio.sleep(2.0)
            if not self._is_challenge(page.url):
                # Leaving the checkpoint is not the same as arriving: LinkedIn
                # usually bounces through an interstitial first, so give it a
                # moment to land rather than judging the URL mid-flight.
                try:
                    await page.wait_for_url("**/feed/**", timeout=15000)
                except PWTimeout:
                    pass
                logger.info("linkedin_challenge_cleared", url=page.url)
                # The solve usually mints a fresh session — keep it.
                await self._persist_session(page.context)
                return
        shot = await self._dump_debug(page, "challenge-timeout")
        raise ProviderError(
            f"The LinkedIn security check was not solved within {timeout_s}s. Run the "
            "search again and complete the check in the browser window (raise "
            f"SCRAPE_CHALLENGE_TIMEOUT_S if you need longer). Screenshot: {shot}."
        )

    # Login field ids differ by page variant: /login uses #username/#password,
    # the homepage/authwall sign-in uses #session_key/#session_password.
    _USER_SELECTORS = ("#username", "#session_key", "input[name='session_key']")
    _PASS_SELECTORS = ("#password", "#session_password", "input[name='session_password']")

    async def _present(self, page: Page, selectors: tuple[str, ...]) -> str | None:
        """First selector currently in the DOM, without waiting."""
        for sel in selectors:
            try:
                if await page.locator(sel).count() > 0:
                    return sel
            except Exception:  # noqa: BLE001
                pass
        return None

    async def _first_present(
        self, page: Page, selectors: tuple[str, ...], timeout_ms: int = 12000
    ) -> str | None:
        deadline = time.monotonic() + timeout_ms / 1000
        while time.monotonic() < deadline:
            if (sel := await self._present(page, selectors)) is not None:
                return sel
            await asyncio.sleep(0.3)
        return None

    async def _resolve_login_page(self, page: Page) -> tuple[str, str] | None:
        """Wait for LinkedIn to settle on the feed, a checkpoint, or the login form.

        LinkedIn redirects lazily: a checkpoint routinely lands *while* we are
        already waiting for the login form, so a single up-front URL check races
        it and loses — the form times out and the checkpoint gets misreported as
        "no login form". Poll all three outcomes together instead, and hand any
        checkpoint to the human before concluding the form is missing.

        Returns the (user, password) selectors to fill, or ``None`` when we are
        already authenticated and no login is needed.
        """
        deadline = time.monotonic() + 20.0
        challenges_seen = 0
        while time.monotonic() < deadline:
            # Checked first and every pass: a restriction is terminal, and it can
            # land mid-wait exactly like a checkpoint does.
            await self._raise_if_restricted(page)

            if "/feed" in page.url and not self._is_blocked(page.url):
                return None

            # Re-checked every pass, so a redirect mid-wait is still caught.
            if self._is_challenge(page.url):
                if challenges_seen >= 3:
                    raise ProviderError(
                        "LinkedIn kept returning security checkpoints even after they "
                        "were solved — it is refusing this automated browser."
                    )
                challenges_seen += 1
                await self._await_human_challenge(page)
                deadline = time.monotonic() + 20.0  # fresh budget after a solve
                continue

            user_sel = await self._present(page, self._USER_SELECTORS)
            pass_sel = await self._present(page, self._PASS_SELECTORS)
            if user_sel and pass_sel:
                return user_sel, pass_sel

            await asyncio.sleep(0.4)

        if self._is_challenge(page.url):
            await self._await_human_challenge(page)
            return await self._resolve_login_page(page)
        return None if "/feed" in page.url else await self._no_form_error(page)

    async def _no_form_error(self, page: Page) -> tuple[str, str]:
        shot = await self._dump_debug(page, "login-no-form")
        title = await page.title()
        raise ProviderError(
            "LinkedIn did not show a login form to the automated browser — it "
            f"served '{title}' at {page.url} instead (likely a bot challenge, "
            f"CAPTCHA, or consent wall). See the debug screenshot: {shot}. "
            "Try running headed (SCRAPE_HEADLESS=false) and solving any challenge "
            "manually, or switch to a compliant data provider."
        )

    async def _dismiss_cookie_banner(self, page: Page) -> None:
        for sel in (
            "button[action-type='ACCEPT']",
            "button:has-text('Accept')",
            "button:has-text('Agree')",
        ):
            try:
                btn = page.locator(sel).first
                if await btn.count() > 0:
                    await btn.click(timeout=2000)
                    await asyncio.sleep(0.4)
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

    async def _login(self, page: Page) -> None:
        username = self._credentials.get("username")
        password = self._credentials.get("password")
        if not username or not password:
            raise ProviderError(
                "The Playwright provider needs LinkedIn credentials. Connect an "
                "account first on the Connect LinkedIn page (Settings)."
            )
        logger.info("linkedin_login_attempt")
        await page.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
        await self._dismiss_cookie_banner(page)

        # Settles the feed / checkpoint / form race in one place, waiting for a
        # human on any checkpoint. None => a live session already got us in.
        selectors = await self._resolve_login_page(page)
        if selectors is None:
            logger.info("linkedin_session_reused")
            return
        user_sel, pass_sel = selectors

        await page.fill(user_sel, username)
        await self._human_delay()
        await page.fill(pass_sel, password)
        await self._human_delay()
        await page.click("button[type=submit]")
        try:
            await page.wait_for_url("**/feed/**", timeout=30000)
        except PWTimeout as exc:
            # 2FA/CAPTCHA after submitting credentials: wait for a human instead of
            # failing, then confirm we actually reached the feed.
            if self._is_challenge(page.url):
                await self._await_human_challenge(page)
                if "/feed" not in page.url or self._is_blocked(page.url):
                    shot = await self._dump_debug(page, "login-post-challenge")
                    raise ProviderError(
                        "The LinkedIn security check was cleared but the session still "
                        f"did not reach the feed (landed on {page.url}). Debug: {shot}."
                    ) from exc
            else:
                shot = await self._dump_debug(page, "login-post-submit")
                raise ProviderError(
                    "LinkedIn login did not complete — wrong credentials or a block "
                    f"page. Landed on {page.url}. Debug screenshot: {shot}."
                ) from exc
        await self._persist_session(page.context)
        logger.info("linkedin_login_success")

    async def _guard_not_blocked(self, page: Page) -> None:
        if self._is_blocked(page.url):
            raise ProviderError(
                f"LinkedIn redirected to a login/authwall page ({page.url}); the "
                "session is invalid or the account is rate-limited."
            )

    # --- search ------------------------------------------------------------

    def _keywords(self, criteria: SearchCriteria) -> str:
        # LinkedIn filters location by a resolved geo facet (geoUrn), not free text.
        # Without its private typeahead API we can only fold location into the
        # keyword query — this biases results toward the location but does NOT
        # strictly filter to it. Proper geo filtering needs a structured provider.
        parts = [criteria.job_title, *criteria.keywords, criteria.location]
        return " ".join(p for p in parts if p and p.strip())

    def _require_auth_material(self) -> None:
        """Fail before launching a browser if we can't possibly authenticate."""
        has_creds = bool(self._credentials.get("username") and self._credentials.get("password"))
        if not has_creds and not self._session_state:
            raise ProviderError(
                "No LinkedIn account connected. Add credentials on the Connect "
                "LinkedIn page (Settings) before running a LinkedIn search."
            )

    async def search(self, criteria: SearchCriteria) -> list[SearchHit]:
        self._require_auth_material()
        context = await self._get_context()
        page = await context.new_page()
        try:
            await self._ensure_authenticated(page)
            keywords = self._keywords(criteria)
            hits: dict[str, SearchHit] = {}
            page_num = 1
            while len(hits) < criteria.max_results and page_num <= 10:
                url = (
                    "https://www.linkedin.com/search/results/people/"
                    f"?keywords={quote_plus(keywords)}&page={page_num}"
                )
                await page.goto(url, wait_until="domcontentloaded")
                await self._guard_not_blocked(page)
                await self._human_delay()
                await self._autoscroll(page)
                found = await self._extract_hits(page)
                if not found:
                    break
                for hit in found:
                    hits.setdefault(hit.source_profile_url, hit)
                page_num += 1
            logger.info("linkedin_search_done", found=len(hits))
            return list(hits.values())[: criteria.max_results]
        finally:
            await page.close()

    async def _autoscroll(self, page: Page, steps: int = 3) -> None:
        """Nudge lazy-loaded content into the DOM before extracting."""
        for _ in range(steps):
            await page.mouse.wheel(0, 1600)
            await asyncio.sleep(random.uniform(0.4, 0.9))

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
        context = await self._get_context()
        page = await context.new_page()
        try:
            await page.goto(hit.source_profile_url, wait_until="domcontentloaded")
            await self._guard_not_blocked(page)
            # LinkedIn's authenticated profile DOM is obfuscated (no <h1>, no stable
            # classes, no JSON-LD). Wait for <main> to exist, then extract what we
            # reliably can — the name is always in the page <title>.
            try:
                await page.wait_for_selector("main", timeout=20000)
            except PWTimeout as exc:
                raise ProfileUnavailableError(
                    f"Profile did not load: {hit.source_profile_url}"
                ) from exc
            await self._human_delay()
            await self._autoscroll(page, steps=4)

            title = await page.title()
            name = title.split("|")[0].strip() or hit.name or "Unknown"
            headline = (
                await _text(page.locator("div.text-body-medium").first)
                or hit.headline
            )
            location = (
                await _text(page.locator("span.text-body-small.inline.t-black--light").first)
                or hit.location
            )
            about = await self._extract_about(page)
            experience = await self._extract_experience(page)
            skills = await self._extract_skills(page)

            # A profile that yields nothing but a name means every selector below
            # missed — the page loaded, so this is selector drift, not a bad URL.
            # Dump the DOM that beat them: it is the only way to retune them, and
            # silently storing an empty profile is what made every scraped
            # candidate score a meaningless flat 30.
            if not any((headline, about, experience, skills)):
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
                current_company=(
                    experience[0].company if experience else hit.current_company
                ),
                location=location or hit.location,
                about=about,
                experience=experience,
                skills=skills,
            )
        finally:
            await page.close()

    async def _extract_about(self, page: Page) -> str | None:
        for sel in (
            "section:has(#about) span[aria-hidden='true']",
            "section:has(div#about) .inline-show-more-text",
            "section:has(div#about)",
        ):
            text = await _text(page.locator(sel).first)
            if text:
                # Strip a leading "About" heading if the whole section was grabbed.
                return text.removeprefix("About").strip() or None
        return None

    async def _extract_experience(self, page: Page) -> list[ExperienceItem]:
        items: list[ExperienceItem] = []
        rows = page.locator("section:has(#experience) li.artdeco-list__item")
        for i in range(min(await rows.count(), 15)):
            row = rows.nth(i)
            spans = row.locator("span[aria-hidden='true']")
            title = await _text(spans.nth(0))
            company = await _text(spans.nth(1))
            date_range = await _find_date_span(spans)
            start, end = _split_dates(date_range)
            if title:
                items.append(
                    ExperienceItem(title=title, company=company, start=start, end=end)
                )
        return items

    async def _extract_skills(self, page: Page) -> list[str]:
        skills: list[str] = []
        rows = page.locator("section:has(#skills) span[aria-hidden='true']")
        for i in range(min(await rows.count(), 50)):
            text = await _text(rows.nth(i))
            if text and text not in skills and len(text) < 60:
                skills.append(text)
        return skills


# --- small helpers ---------------------------------------------------------

async def _text(locator: Locator) -> str | None:
    try:
        if await locator.count() == 0:
            return None
        value = (await locator.first.inner_text()).strip()
        return value or None
    except Exception:  # noqa: BLE001 — extraction is best-effort
        return None


async def _find_date_span(spans: Locator) -> str | None:
    """Find the span that looks like a date range among a role's text spans."""
    for i in range(min(await spans.count(), 6)):
        text = await _text(spans.nth(i))
        if text and any(ch.isdigit() for ch in text) and (
            "-" in text or "–" in text or "present" in text.lower()
        ):
            return text
    return None


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
