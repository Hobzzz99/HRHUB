"""Keeping the browser window out of the way until a person is actually needed.

Scraping runs in a **headed** browser, because LinkedIn detects headless
Chromium far more readily and the account is the scarce resource. But a window
that steals focus every few minutes makes the machine unusable for the recruiter
sitting at it, and there is nothing for them to watch: the run is automated
except for sign-in and the occasional CAPTCHA.

So the window is minimised for the whole run and restored only at the two
moments a human has to act. Both go through ``_wait_for_human``, which is the
one place that blocks on a person, so revealing there covers first sign-in and a
mid-run challenge alike.

Everything here is best-effort. The window is a convenience, not part of the
result, so a failure to move it must never end a search — each call swallows its
own errors and logs them.
"""

from __future__ import annotations

from playwright.async_api import Page

from app.core.logging import get_logger

logger = get_logger(__name__)


#: Where the window goes to be out of sight. Far enough left of the desktop that
#: no monitor arrangement reaches it, while staying a coordinate Windows accepts.
_OFFSCREEN_LEFT = -32000
_OFFSCREEN_TOP = 0


async def _set_bounds(page: Page, bounds: dict) -> None:
    """Ask Chromium to move this page's window, over CDP.

    Playwright has no window-management API, so this drops to the DevTools
    protocol. Chromium-only, which is the only engine this project drives.
    """
    session = await page.context.new_cdp_session(page)
    try:
        target = await session.send("Browser.getWindowForTarget")
        window_id = target["windowId"]
        # A minimised window must be restored before it can be positioned, and
        # setting state and position in one call is rejected.
        await session.send(
            "Browser.setWindowBounds",
            {"windowId": window_id, "bounds": {"windowState": "normal"}},
        )
        if bounds:
            await session.send(
                "Browser.setWindowBounds", {"windowId": window_id, "bounds": bounds}
            )
    finally:
        await session.detach()


async def conceal(page: Page) -> None:
    """Move the window off-screen so the recruiter never sees it.

    Deliberately *not* minimised. A minimised window on Windows stops
    compositing, and LinkedIn renders its results and filter pills lazily —
    they need the page to actually paint. Minimising left every search sitting
    on skeleton placeholders forever, signed in and stuck.

    Off-screen keeps the window in its normal state, so Chromium paints it
    exactly as if it were visible; it simply sits at coordinates no monitor
    covers.
    """
    try:
        await _set_bounds(page, {"left": _OFFSCREEN_LEFT, "top": _OFFSCREEN_TOP})
        logger.info("browser_window_concealed")
    except Exception as exc:  # noqa: BLE001 - cosmetic; never fail a search for it
        logger.info("browser_window_conceal_failed", error=str(exc))


async def reveal(page: Page, *, left: int = 80, top: int = 60) -> None:
    """Bring the window back on-screen and focus it, because a person is needed.

    Positioning before focusing matters: raising a window that is still parked
    off-screen puts it in front of nothing anybody can see.
    """
    try:
        await _set_bounds(page, {"left": left, "top": top})
        await page.bring_to_front()
        logger.info("browser_window_revealed")
    except Exception as exc:  # noqa: BLE001 - the operator can raise it by hand
        logger.warning("browser_window_reveal_failed", error=str(exc))
