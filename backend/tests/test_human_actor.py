"""Regression tests for the two page-interaction bugs found in live-browser runs.

Both were invisible to the pure-motion tests and silently produced clicks that
landed on the wrong element — the worst possible failure mode for a scraper,
because it looks like selector drift rather than a timing bug. Neither needs a
browser to pin down: what matters is the contract of the code that reads scroll
state and the hit-test, so the page is stubbed.
"""

from __future__ import annotations

from app.providers.human import HumanActor


class _FakeMouse:
    def __init__(self) -> None:
        self.moves: list[tuple[float, float]] = []

    async def move(self, x, y):
        self.moves.append((x, y))

    async def wheel(self, dx, dy):
        pass


class _FakePage:
    """Enough of a Playwright ``Page`` for the actor's scroll/hit-test paths."""

    viewport_size = {"width": 1440, "height": 900}

    def __init__(self, scroll_sequence: list[float]) -> None:
        # Successive values window.scrollY will report, simulating a scroll that
        # is still being applied when the first reads come in.
        self._sequence = list(scroll_sequence)
        self.reads = 0
        self.mouse = _FakeMouse()

    async def evaluate(self, expression, *args):
        assert "scrollY" in expression
        self.reads += 1
        if len(self._sequence) > 1:
            return self._sequence.pop(0)
        return self._sequence[0]


async def test_settle_scroll_waits_out_a_scroll_that_starts_late():
    # The failure this pins: mouse.wheel returns before the scroll is applied,
    # so the first two reads are both the *old* position. Returning there hands
    # back a stale bounding box and the click lands on whatever is at the old
    # coordinates. Settling must not stop until the value truly stops changing.
    page = _FakePage([0, 0, 40, 120, 180, 180, 180])
    actor = HumanActor(page)  # type: ignore[arg-type]
    await actor._settle_scroll()
    assert page.reads >= 6
    assert await page.evaluate("() => window.scrollY") == 180


async def test_settle_scroll_gives_up_rather_than_hanging():
    # A page that never stops moving (infinite scroll, animation) must not park
    # the worker forever.
    page = _FakePage([float(i) for i in range(10_000)])
    actor = HumanActor(page)  # type: ignore[arg-type]
    await actor._settle_scroll(timeout_s=0.3)


async def test_pointer_hit_test_never_accepts_an_ancestor():
    """An ancestor hit must NOT count as being over the target.

    ``elementFromPoint`` returns ``<body>`` for empty space, and body contains
    every element — so an ``hit.contains(el)`` arm makes the check pass for any
    point on the page. That is how a click aimed at nothing got reported as on
    target. Asserted against the shipped JS, since only the browser can run it.
    """
    captured: list[str] = []

    class _Locator:
        async def evaluate(self, expression, arg):
            captured.append(expression)
            return True

    actor = HumanActor(_FakePage([0]))  # type: ignore[arg-type]
    assert await actor._pointer_is_over(_Locator()) is True  # type: ignore[arg-type]

    js = captured[0]
    assert "elementFromPoint" in js
    assert "hit === el" in js
    assert "el.contains(hit)" in js
    assert "hit.contains(el)" not in js


async def test_pointer_hit_test_is_asked_about_the_current_pointer():
    seen: list[list[float]] = []

    class _Locator:
        async def evaluate(self, expression, arg):
            seen.append(arg)
            return True

    actor = HumanActor(_FakePage([0]))  # type: ignore[arg-type]
    await actor.move_to_point((321.0, 654.0))
    await actor._pointer_is_over(_Locator())  # type: ignore[arg-type]
    assert seen == [[321.0, 654.0]]


async def test_pointer_hit_test_treats_an_error_as_a_miss():
    class _Locator:
        async def evaluate(self, expression, arg):
            raise RuntimeError("element detached")

    actor = HumanActor(_FakePage([0]))  # type: ignore[arg-type]
    assert await actor._pointer_is_over(_Locator()) is False  # type: ignore[arg-type]
