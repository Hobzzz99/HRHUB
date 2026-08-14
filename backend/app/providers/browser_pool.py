"""Browser lifecycle for the Playwright provider.

**One browser per search.** Each search runs in its own asyncio event loop
(`asyncio.run` per Celery task / eager call), and a Playwright connection is bound
to the loop that created it — so a browser cannot be safely reused across searches.
Each provider instance therefore owns a fresh `BrowserPool`, launches Chromium
within the search's loop, and closes it in `aclose()`. Re-login is avoided via the
persisted, encrypted `storageState` (not by reusing the browser process).

Contexts are built by `app.providers.fingerprint`, which keeps the UA, client
hints, `navigator`, WebGL and timezone telling one consistent story and installs
the stealth init script before any page script runs.

This module is only imported when `PROVIDER=linkedin`.
"""

from __future__ import annotations

import asyncio
import os

from playwright.async_api import Browser, BrowserContext, async_playwright

from app.core.config import settings
from app.core.logging import get_logger
from app.providers import fingerprint

logger = get_logger(__name__)


class BrowserPool:
    """Owns one Chromium instance for the lifetime of a single search.

    ``fingerprint_seed`` pins which machine this browser presents. Pass the
    provider-account row id so each connected account keeps one stable identity
    and two accounts never share hardware — see `fingerprint.derive_profile`.
    """

    def __init__(self, *, fingerprint_seed: str | None = None) -> None:
        self._playwright = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()
        self._seed = fingerprint_seed

    def _profile(self) -> fingerprint.FingerprintProfile:
        """This pool's machine, re-pinned to the engine that is actually running.

        Derivation is pure, so calling it before and after launch yields the
        same machine; only the Chrome version differs, and that is taken from
        the live binary rather than guessed.
        """
        version = self._browser.version if self._browser else None
        return fingerprint.derive_profile(self._seed).with_engine_version(version)

    async def start(self) -> None:
        async with self._lock:
            if self._browser and self._browser.is_connected():
                return
            # Point the driver at a custom browser location if configured (set
            # before the driver subprocess starts so it inherits the value).
            if settings.playwright_browsers_path:
                os.environ.setdefault(
                    "PLAYWRIGHT_BROWSERS_PATH", settings.playwright_browsers_path
                )
            logger.info("browser_pool_starting", headless=settings.scrape_headless)
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=settings.scrape_headless,
                args=fingerprint.launch_args(
                    headless=settings.scrape_headless, profile=self._profile()
                ),
                # Drops Playwright's own --enable-automation switch, which sets
                # navigator.webdriver and shows the automation infobar.
                ignore_default_args=fingerprint.IGNORE_DEFAULT_ARGS,
                # A person is going to sign in and clear CAPTCHAs in this window;
                # don't let Playwright's default 30s budget close it underneath them.
                timeout=120_000,
            )
            logger.info("browser_fingerprint", profile=fingerprint.describe(self._profile()))

    async def _ensure_browser(self) -> Browser:
        if not self._browser or not self._browser.is_connected():
            await self.start()
        assert self._browser is not None
        return self._browser

    async def new_context(self, storage_state: dict | None = None) -> BrowserContext:
        """Create a fingerprint-consistent context, optionally restoring a session."""
        browser = await self._ensure_browser()
        locale = settings.scrape_locale
        profile = self._profile()
        if not settings.scrape_stealth:
            # Plain Chromium: no spoofed hardware, no patched navigator. Slower
            # to draw suspicion over many requests, but it is what a real
            # browser looks like to a fingerprint check — which is what sign-in
            # CAPTCHAs actually run.
            logger.info("browser_context_without_stealth")
            return await browser.new_context(
                storage_state=storage_state,
                locale=locale,
                timezone_id=settings.scrape_timezone or None,
            )

        context = await browser.new_context(
            storage_state=storage_state,
            **fingerprint.context_options(
                profile=profile,
                timezone_id=settings.scrape_timezone or None,
                locale=locale,
            ),
        )
        # Must be added before any navigation so it wins the race with page
        # scripts that fingerprint on load.
        await context.add_init_script(
            fingerprint.stealth_script(profile=profile, locale=locale)
        )
        return context

    async def close(self) -> None:
        async with self._lock:
            if self._browser:
                try:
                    await self._browser.close()
                except Exception:  # noqa: BLE001 — best-effort teardown
                    pass
                self._browser = None
            if self._playwright:
                try:
                    await self._playwright.stop()
                except Exception:  # noqa: BLE001 — best-effort teardown
                    pass
                self._playwright = None
