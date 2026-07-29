"""Drives a Playwright ``Page`` the way a person drives a browser.

This module is the only place that turns the plans from
:mod:`app.providers.human_motion` into real input events, plus the safety gate
that refuses to touch elements a human could not have touched.

Nothing here makes scraping *safe* — it makes the input stream look like input
rather than teleportation. The hard limits (20 profiles/hour, manual login,
manual CAPTCHA) are what actually keep the account out of trouble.

Two rules the rest of the provider relies on:

* Every user-visible action goes through :meth:`HumanActor.settle` first, so
  pacing, long pauses and micro-breaks are applied uniformly and cannot be
  forgotten at a call site.
* :meth:`HumanActor.click` runs the 10-point honeypot check and raises rather
  than clicking a trap. Pass ``enforce_honeypot=False`` only for elements whose
  provenance you already trust.
"""

from __future__ import annotations

import asyncio
import time
from random import Random

from playwright.async_api import Locator, Page

from app.core.logging import get_logger
from app.providers.human_motion import (
    BACKSPACE,
    PacingProfile,
    Point,
    lognormal_delay,
    mouse_path,
    next_break_after,
    scroll_plan,
    think_delay,
    typing_plan,
)

logger = get_logger(__name__)


class HoneypotError(RuntimeError):
    """An element failed the honeypot check; interacting with it would be a tell."""

    def __init__(self, flags: list[str]) -> None:
        self.flags = flags
        super().__init__(f"element looks like a honeypot ({', '.join(flags)})")


# --- the 10-point honeypot check -------------------------------------------

# Ten independent reasons a real user could never have interacted with an
# element. Bot traps rely on automation clicking things humans cannot see, so
# any single hit is disqualifying. Evaluated in-page because every one of these
# needs computed style and layout, which only the browser knows.
#
#   1 display_none        2 visibility_hidden   3 opacity_near_zero
#   4 zero_size           5 offscreen_position  6 negative_z_index
#   7 aria_hidden         8 suspicious_name     9 hidden_or_untabbable
#  10 clipped_or_inert
_HONEYPOT_JS = r"""
(el) => {
  const flags = [];
  const style = getComputedStyle(el);
  const rect = el.getBoundingClientRect();
  const root = document.documentElement;

  // 1 — removed from layout entirely, on the element or any ancestor.
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    if (getComputedStyle(n).display === 'none') { flags.push('display_none'); break; }
  }

  // 2 — painted nowhere.
  if (style.visibility === 'hidden' || style.visibility === 'collapse') {
    flags.push('visibility_hidden');
  }

  // 3 — transparent. Opacity multiplies down the tree, so accumulate it.
  let opacity = 1;
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    const o = parseFloat(getComputedStyle(n).opacity);
    if (!Number.isNaN(o)) opacity *= o;
  }
  if (opacity < 0.1) flags.push('opacity_near_zero');

  // 4 — too small to aim at.
  if (rect.width < 2 || rect.height < 2) flags.push('zero_size');

  // 5 — parked outside the document (the classic `left: -9999px`). Being merely
  //     below the fold is normal and must NOT trip this, so compare against
  //     document coordinates rather than the viewport.
  const absLeft = rect.left + window.scrollX;
  const absTop = rect.top + window.scrollY;
  const docW = Math.max(root.scrollWidth, window.innerWidth);
  const docH = Math.max(root.scrollHeight, window.innerHeight);
  if (absLeft + rect.width < 0 || absTop + rect.height < 0 ||
      absLeft > docW || absTop > docH) {
    flags.push('offscreen_position');
  }

  // 6 — stacked behind the page.
  for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
    const z = parseInt(getComputedStyle(n).zIndex, 10);
    if (!Number.isNaN(z) && z < 0) { flags.push('negative_z_index'); break; }
  }

  // 7 — explicitly hidden from the accessibility tree, i.e. from real users.
  if (el.closest('[aria-hidden="true"], [hidden], [inert]')) flags.push('aria_hidden');

  // 8 — named like a trap.
  const trapWords = new RegExp([
    'honey', '\\bhp[-_]', '[-_]hp\\b', '\\btrap', '\\bdecoy', '\\bdummy',
    'fake[-_]?(input|field)', 'nofill', 'do[-_]?not[-_]?fill',
    'leave[-_]?(this|it)[-_]?(blank|empty)', 'bot[-_]?(field|check)',
  ].join('|'), 'i');
  const naming = [
    el.id,
    el.getAttribute('name'),
    typeof el.className === 'string' ? el.className : '',
    el.getAttribute('placeholder'),
    el.getAttribute('data-testid'),
    el.getAttribute('autocomplete'),
  ].filter(Boolean).join(' ');
  if (trapWords.test(naming)) flags.push('suspicious_name');

  // 9 — a control the keyboard can never reach.
  const interactive = ['INPUT', 'BUTTON', 'A', 'SELECT', 'TEXTAREA'].includes(el.tagName);
  if (el.tagName === 'INPUT' && el.type === 'hidden') flags.push('hidden_or_untabbable');
  else if (interactive && el.tabIndex < 0) flags.push('hidden_or_untabbable');

  // 10 — visually present but physically unusable.
  const clip = style.clip || '';
  const clipPath = style.clipPath || '';
  const transform = style.transform || '';
  if (/rect\(\s*0(px)?[, ]/.test(clip) || /inset\(\s*(100%|50%)/.test(clipPath) ||
      style.pointerEvents === 'none' || /matrix\(0,\s*0,\s*0,\s*0/.test(transform) ||
      /scale\(0\)/.test(transform)) {
    flags.push('clipped_or_inert');
  }

  return flags;
}
"""

#: The traps :data:`_HONEYPOT_JS` tests for, in the order the script checks them.
#: Asserted against the script in tests so a rule cannot go missing unnoticed.
HONEYPOT_CHECKS = (
    "display_none",
    "visibility_hidden",
    "opacity_near_zero",
    "zero_size",
    "offscreen_position",
    "negative_z_index",
    "aria_hidden",
    "suspicious_name",
    "hidden_or_untabbable",
    "clipped_or_inert",
)


async def honeypot_flags(locator: Locator) -> list[str]:
    """Which of the 10 traps ``locator`` trips. Empty means safe to touch."""
    try:
        flags = await locator.evaluate(_HONEYPOT_JS)
    except Exception:  # noqa: BLE001 — a detached/odd node is not proof of a trap
        logger.debug("honeypot_check_failed", exc_info=True)
        return []
    return list(dict.fromkeys(flags or []))


# --- the actor -------------------------------------------------------------


class HumanActor:
    """Human-shaped input for one page.

    Hold one per page (or per context) so pacing state — pointer position, the
    action counter driving micro-breaks, the session's typing speed — is
    continuous across the whole visit rather than resetting per call.
    """

    def __init__(
        self,
        page: Page,
        *,
        rng: Random | None = None,
        profile: PacingProfile | None = None,
    ) -> None:
        self._page = page
        self._rng = rng or Random()
        self._profile = profile or PacingProfile()
        # A session has one typing speed, not one per field.
        self._wpm = self._rng.uniform(*self._profile.wpm_range)
        self._actions_until_break = next_break_after(self._rng, self._profile)
        viewport = page.viewport_size or {"width": 1366, "height": 768}
        self._bounds: tuple[float, float] = (viewport["width"], viewport["height"])
        # Start somewhere plausible rather than at (0, 0), which no real pointer is.
        self._pointer: Point = (
            self._rng.uniform(0.2, 0.8) * self._bounds[0],
            self._rng.uniform(0.2, 0.8) * self._bounds[1],
        )

    @property
    def page(self) -> Page:
        return self._page

    @property
    def rng(self) -> Random:
        return self._rng

    # --- pacing ------------------------------------------------------------

    async def settle(self) -> None:
        """Pause before the next action, taking a micro-break when one is due."""
        self._actions_until_break -= 1
        if self._actions_until_break <= 0:
            pause = lognormal_delay(self._profile.break_median_s, self._rng, sigma=0.55)
            logger.debug("human_micro_break", seconds=round(pause, 2))
            await asyncio.sleep(pause)
            self._actions_until_break = next_break_after(self._rng, self._profile)
            return
        await asyncio.sleep(think_delay(self._rng, self._profile))

    async def dwell(self, median_s: float) -> None:
        """A one-off pause — reading a section, waiting for something to render."""
        await asyncio.sleep(lognormal_delay(median_s, self._rng))

    # --- pointer -----------------------------------------------------------

    async def move_to_point(self, target: Point, *, target_size: float = 24.0) -> None:
        path = mouse_path(
            self._pointer,
            target,
            self._rng,
            target_size=target_size,
            bounds=self._bounds,
        )
        for step in path:
            await asyncio.sleep(step.delay)
            await self._page.mouse.move(step.x, step.y)
        self._pointer = target

    async def move_to(self, locator: Locator) -> None:
        """Move the pointer onto ``locator``, scrolling it into view if needed."""
        box = await self._bring_into_view(locator)
        if box is None:
            return
        await self.move_to_point(
            self._aim_inside(box), target_size=min(box["width"], box["height"])
        )

    def _aim_inside(self, box: dict) -> Point:
        """A believable landing point: near the centre, never exactly on it."""
        return (
            box["x"] + box["width"] * _clamp01(self._rng.gauss(0.5, 0.16)),
            box["y"] + box["height"] * _clamp01(self._rng.gauss(0.5, 0.18)),
        )

    async def _bring_into_view(self, locator: Locator) -> dict | None:
        """Scroll ``locator`` into the viewport with wheel events, not a jump.

        ``scroll_into_view_if_needed`` teleports the scroll position in a single
        frame, which no wheel or trackpad can do; it is only used as a fallback
        when the element has no box to aim at.
        """
        box = await locator.bounding_box()
        if box is None:
            try:
                await locator.scroll_into_view_if_needed(timeout=5000)
            except Exception:  # noqa: BLE001
                return None
            return await locator.bounding_box()

        height = self._bounds[1]
        # Park the element in the comfortable middle of the screen, not the edge.
        preferred = height * self._rng.uniform(0.30, 0.55)
        delta = int(box["y"] - preferred)
        if abs(delta) > 40:
            await self.scroll_by(delta)
            box = await locator.bounding_box()
        return box

    async def click(self, locator: Locator, *, enforce_honeypot: bool = True) -> None:
        """Move to ``locator``, hesitate, and press — refusing obvious traps."""
        flags = await honeypot_flags(locator)
        if flags:
            logger.warning("honeypot_detected", flags=flags)
            if enforce_honeypot:
                raise HoneypotError(flags)

        await self.move_to(locator)
        if not await self._pointer_is_over(locator):
            # Lazily-hydrated content shifts under the pointer between aiming and
            # pressing. Re-aim once; if the target still is not under the cursor,
            # a synthetic click is better than silently clicking whatever moved
            # into its place.
            logger.debug("human_click_reaim")
            await self.move_to(locator)
            if not await self._pointer_is_over(locator):
                logger.warning("human_click_fallback")
                await locator.click(timeout=10000)
                return

        # The beat between arriving and committing — pure hesitation.
        await asyncio.sleep(lognormal_delay(self._profile.hesitation_median_s, self._rng))
        await self._page.mouse.down()
        await asyncio.sleep(self._rng.uniform(0.045, 0.135))  # button dwell
        await self._page.mouse.up()

    async def _pointer_is_over(self, locator: Locator) -> bool:
        """Whether the element under the cursor is ``locator`` or inside it.

        Note the asymmetry: a hit on a *descendant* counts (clicking the span
        inside a button is still clicking the button), but a hit on an
        *ancestor* does not. `elementFromPoint` returns `<body>` for empty
        space, and body contains everything — accepting ancestors would make
        this check pass for any point on the page and assert nothing at all.
        """
        try:
            return bool(
                await locator.evaluate(
                    """(el, point) => {
                        const hit = document.elementFromPoint(point[0], point[1]);
                        return !!hit && (hit === el || el.contains(hit));
                    }""",
                    list(self._pointer),
                )
            )
        except Exception:  # noqa: BLE001 — treat an unanswerable check as a miss
            return False

    async def wander(self) -> None:
        """Drift the pointer somewhere idle — what hands do while eyes read."""
        target = (
            _clamp(self._rng.gauss(self._pointer[0], 180), 4, self._bounds[0] - 4),
            _clamp(self._rng.gauss(self._pointer[1], 140), 4, self._bounds[1] - 4),
        )
        await self.move_to_point(target, target_size=140.0)

    # --- keyboard ----------------------------------------------------------

    async def type_into(self, locator: Locator, text: str) -> None:
        """Focus ``locator`` and type ``text`` at this session's speed, typos included."""
        await self.click(locator)
        await asyncio.sleep(lognormal_delay(0.28, self._rng))
        keyboard = self._page.keyboard
        for event in typing_plan(text, self._rng, wpm=self._wpm, profile=self._profile):
            await asyncio.sleep(event.delay)
            if event.key == BACKSPACE:
                await keyboard.press("Backspace")
            else:
                await keyboard.type(event.key)

    # --- scrolling ---------------------------------------------------------

    async def scroll_by(self, pixels: int) -> None:
        """Cover ``pixels`` with inertial flicks and a settling nudge."""
        for step in scroll_plan(int(pixels), self._rng, profile=self._profile):
            await asyncio.sleep(step.delay)
            await self._page.mouse.wheel(0, step.delta)
        await self._settle_scroll()

    # How long the scroll position must hold still before it counts as settled.
    # One sample is not enough: a scroll that has not been *applied* yet also
    # reads as unchanged, and mistaking "not started" for "finished" is what
    # produces stale coordinates.
    _SETTLE_SAMPLE_S = 0.05
    _SETTLE_STABLE_SAMPLES = 3
    _SETTLE_LEAD_IN_S = 0.08

    async def _settle_scroll(self, *, timeout_s: float = 2.0) -> None:
        """Wait for the page to stop moving after a flick.

        ``mouse.wheel`` returns as soon as the event is dispatched, *before* the
        scroll it triggers has been applied. Anything that reads a bounding box
        straight afterwards gets stale coordinates — and a click aimed with a
        stale box lands on whatever happens to be at the old position.

        Sampling therefore starts after a short lead-in and only concludes once
        the position has repeated several times, so a late-starting or
        smooth-animated scroll cannot masquerade as a finished one. A page that
        never stops (infinite scroll, animation) falls out on ``timeout_s``.
        """
        await asyncio.sleep(self._SETTLE_LEAD_IN_S)
        deadline = time.monotonic() + timeout_s
        previous: float | None = None
        stable = 0
        while time.monotonic() < deadline:
            try:
                current = await self._page.evaluate("() => window.scrollY")
            except Exception:  # noqa: BLE001 — navigated away mid-scroll
                return
            if current == previous:
                stable += 1
                if stable >= self._SETTLE_STABLE_SAMPLES - 1:
                    return
            else:
                stable = 0
                previous = current
            await asyncio.sleep(self._SETTLE_SAMPLE_S)

    async def read_page(self, *, screens: float = 3.0) -> None:
        """Skim down the page as if reading it, pausing between screenfuls.

        This is what pulls LinkedIn's lazily-hydrated sections into the DOM, and
        it is also the single most human thing a profile visit does: a real
        recruiter reads before they leave.
        """
        viewport_height = self._bounds[1]
        remaining = int(viewport_height * screens)
        while remaining > 0:
            chunk = min(remaining, int(viewport_height * self._rng.uniform(0.55, 0.95)))
            await self.scroll_by(chunk)
            remaining -= chunk
            await asyncio.sleep(lognormal_delay(1.1, self._rng, sigma=0.55))
            if self._rng.random() < 0.35:
                await self.wander()
            # Re-reading something above is normal; a strictly monotonic scroll
            # down a long page is not.
            if self._rng.random() < 0.18:
                await self.scroll_by(-self._rng.randint(120, 400))
                await asyncio.sleep(lognormal_delay(0.9, self._rng))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clamp01(value: float) -> float:
    return _clamp(value, 0.08, 0.92)
