"""Browser lifecycle for the Playwright provider.

**One browser per search.** Each search runs in its own asyncio event loop
(`asyncio.run` per Celery task / eager call), and a Playwright connection is bound
to the loop that created it — so a browser cannot be safely reused across searches.
Each provider instance therefore owns a fresh `BrowserPool`, launches Chromium
within the search's loop, and closes it in `aclose()`. Re-login is avoided via the
persisted, encrypted `storageState` (not by reusing the browser process).

This module is only imported when `PROVIDER=playwright`.
"""

from __future__ import annotations

import asyncio
import os

from playwright.async_api import Browser, BrowserContext, async_playwright

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class BrowserPool:
    """Process-wide singleton wrapping one Chromium instance."""

    def __init__(self) -> None:
        self._playwright = None
        self._browser: Browser | None = None
        self._lock = asyncio.Lock()

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
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-features=IsolateOrigins,site-per-process",
                    "--start-maximized",
                ],
            )

    async def _ensure_browser(self) -> Browser:
        if not self._browser or not self._browser.is_connected():
            await self.start()
        assert self._browser is not None
        return self._browser

    async def new_context(self, storage_state: dict | None = None) -> BrowserContext:
        """Create an isolated context (one per task), optionally restoring a session."""
        browser = await self._ensure_browser()
        return await browser.new_context(
            storage_state=storage_state,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            viewport={"width": 1366, "height": 768},
            locale="en-US",
        )

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
                except Exception:  # noqa: BLE001
                    pass
                self._playwright = None
