"""A logged-out browser session must never be saved over a working one.

The bug this guards: `aclose()` persisted the session unconditionally, so a run
that ended before sign-in finished overwrote a good login with a logged-out
state. The next run then had to sign in again — and if that also failed, it
saved another bad state. The fault fed itself, and the operator saw an endless
sign-in-and-CAPTCHA loop.
"""

from __future__ import annotations

import asyncio

from app.providers.playwright_linkedin import PlaywrightLinkedInProvider

SIGNED_IN = {"cookies": [{"name": "li_at", "value": "x"}, {"name": "JSESSIONID", "value": "y"}]}
SIGNED_OUT = {"cookies": [{"name": "JSESSIONID", "value": "y"}, {"name": "bcookie", "value": "z"}]}


class _FakeContext:
    def __init__(self, state):
        self._state = state

    async def storage_state(self):
        return self._state


def _provider_with(state, *, authenticated):
    saved: list[dict] = []

    async def on_update(new_state):
        saved.append(new_state)

    provider = PlaywrightLinkedInProvider(on_session_update=on_update)
    provider._authenticated = authenticated
    return provider, _FakeContext(state), saved


def test_a_signed_in_session_is_saved():
    provider, context, saved = _provider_with(SIGNED_IN, authenticated=True)
    asyncio.run(provider._persist_session(context))
    assert saved == [SIGNED_IN]


def test_a_logged_out_session_is_never_saved():
    """No auth cookie means the browser is not signed in, whatever we believe."""
    provider, context, saved = _provider_with(SIGNED_OUT, authenticated=True)
    asyncio.run(provider._persist_session(context))
    assert saved == [], "a state without li_at must not overwrite a working login"


def test_an_empty_session_is_never_saved():
    provider, context, saved = _provider_with({"cookies": []}, authenticated=False)
    asyncio.run(provider._persist_session(context))
    assert saved == []


def test_closing_before_sign_in_saves_nothing():
    """The exact path that poisoned the stored session."""
    provider, context, saved = _provider_with(SIGNED_OUT, authenticated=False)
    provider._context = context
    asyncio.run(provider.aclose())
    assert saved == []
