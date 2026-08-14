"""The browser window is a convenience, never a reason to lose a search.

Window management runs over CDP, which can fail for reasons that have nothing
to do with the scrape — a closed page, a detached session, a Chromium that
declines the call. None of that is worth ending a run that has already spent
scrape budget, so both helpers swallow their own errors.
"""

from __future__ import annotations

import pytest

from app.providers import window


class _Session:
    def __init__(self, fail_on: str | None = None):
        self.sent: list[str] = []
        self.bounds: list[dict] = []
        self.detached = False
        self._fail_on = fail_on

    async def send(self, method: str, params: dict | None = None):
        self.sent.append(method)
        if params and "bounds" in params:
            self.bounds.append(params["bounds"])
        if method == self._fail_on:
            raise RuntimeError("CDP said no")
        return {"windowId": 7}

    async def detach(self):
        self.detached = True


class _Context:
    def __init__(self, session: _Session):
        self._session = session

    async def new_cdp_session(self, _page):
        return self._session


class _Page:
    def __init__(self, session: _Session):
        self.context = _Context(session)
        self.brought_to_front = False

    async def bring_to_front(self):
        self.brought_to_front = True


@pytest.mark.asyncio
async def test_conceal_moves_the_window_off_screen():
    """Never minimised: a minimised window stops compositing, and LinkedIn's
    lazily drawn results then never render past their skeletons."""
    session = _Session()
    await window.conceal(_Page(session))
    states = [b.get("windowState") for b in session.bounds]
    assert "minimized" not in states
    assert session.bounds[-1]["left"] < -1000


@pytest.mark.asyncio
async def test_conceal_restores_state_before_positioning():
    """A minimised window cannot be positioned until it is restored."""
    session = _Session()
    await window.conceal(_Page(session))
    assert session.bounds[0] == {"windowState": "normal"}


@pytest.mark.asyncio
async def test_reveal_positions_then_focuses():
    """Order matters: raising a window still parked off-screen shows nobody anything."""
    session = _Session()
    page = _Page(session)
    await window.reveal(page)
    assert session.bounds[-1]["left"] >= 0
    assert page.brought_to_front


@pytest.mark.asyncio
async def test_conceal_survives_a_cdp_failure():
    session = _Session(fail_on="Browser.setWindowBounds")
    await window.conceal(_Page(session))  # must not raise
    assert session.detached


@pytest.mark.asyncio
async def test_reveal_survives_a_cdp_failure():
    """A window that will not come forward is worth a warning, not a dead run.

    The operator can still raise it from the taskbar themselves.
    """
    session = _Session(fail_on="Browser.getWindowForTarget")
    await window.reveal(_Page(session))  # must not raise
    assert session.detached
