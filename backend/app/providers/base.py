"""The provider interface.

Implementations must return `SearchHit`s from `search` (cheap card data used for
pre-filtering) and a full `RawProfile` from `fetch_profile`. All scoring lives in
`app.domain`, so providers only extract — they never score.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from enum import StrEnum

from app.domain.models import RawProfile, SearchCriteria, SearchHit

#: Called with a fresh Playwright ``storage_state`` whenever a provider
#: establishes or refreshes a browser session, so it can be encrypted and
#: stored. Lives here rather than in the provider so `search_runner` can type
#: its callback without importing Playwright.
SessionCallback = Callable[[dict], Awaitable[None]]


class ProviderError(RuntimeError):
    """Base class for recoverable provider failures."""


class ProfileUnavailableError(ProviderError):
    """A specific profile could not be fetched (skip it, keep the search going)."""


class AccountRestrictedError(RuntimeError):
    """The platform has locked the account this provider signs in with.

    Deliberately **not** a :class:`ProviderError`. That base means "recoverable,
    skip this profile and continue", and callers handle it that way — so
    inheriting from it would let a restriction be swallowed once per remaining
    profile, re-hitting a locked account exactly when the error text says to
    stop. Being a separate type makes the pipeline handle it or crash, never
    silently continue.
    """


class Degradation(StrEnum):
    """A thing the provider was asked to do and could not.

    These are not errors — the run continued and produced results. They are the
    reasons those results answer a *different question* than the one asked, and
    the recruiter has to be told which.

    Every one of these has already happened in production and been reported to
    the recruiter as "No candidates matched. Try lowering the minimum score."
    """

    #: A requested filter never reached the platform, so the results are not
    #: restricted the way the recruiter asked. The expensive one: the search
    #: spends its whole budget on people who are then all rejected.
    FILTER_NOT_APPLIED = "filter_not_applied"
    #: The search returned so little that a constraint was released to widen it.
    FILTER_RELAXED = "filter_relaxed"
    #: The results list produced no cards at all — usually the page not
    #: rendering rather than the platform genuinely having nobody.
    NO_RESULTS_EXTRACTED = "no_results_extracted"
    #: Profiles opened but came back without the fields scoring depends on.
    PROFILES_INCOMPLETE = "profiles_incomplete"
    #: Profiles could not be opened at all.
    PROFILES_UNREACHABLE = "profiles_unreachable"
    #: The hourly budget ran out part-way, so this is a partial answer.
    BUDGET_EXHAUSTED = "budget_exhausted"


class CandidateProvider(ABC):
    """Abstract candidate source."""

    #: Short identifier stored on candidates (e.g. "mock", "linkedin").
    name: str = "base"

    @property
    def degradations(self) -> list[tuple[Degradation, str]]:
        """What this run could not do, created on first use.

        Lazy rather than set in ``__init__`` so that a provider which does not
        chain to this constructor — every existing one, and any test double —
        still reports rather than raising ``AttributeError`` from inside the
        pipeline's ``finally`` block, where it would mask the real failure.
        Held per instance, so no list is ever shared between runs.
        """
        existing = self.__dict__.get("_degradations")
        if existing is None:
            existing = []
            self.__dict__["_degradations"] = existing
        return existing

    def degraded(self, kind: Degradation, detail: str) -> None:
        """Record that the run could not do something it was asked to.

        Providers call this instead of staying silent. The runner reads it after
        the search and stores it, so the difference between "nobody matched" and
        "we could not apply your filter" survives all the way to the screen.
        """
        self.degradations.append((kind, detail))

    @abstractmethod
    async def search(self, criteria: SearchCriteria) -> list[SearchHit]:
        """Return candidate cards matching the criteria (up to ``max_results``)."""

    @abstractmethod
    async def fetch_profile(self, hit: SearchHit) -> RawProfile:
        """Fetch and extract a full profile for a search hit."""

    async def aclose(self) -> None:  # noqa: B027 — opt-in hook, not a contract
        """Release resources (browser, sessions). Safe no-op by default.

        Deliberately concrete rather than abstract: only the browser-driven
        providers hold anything to release, and forcing `mock`/`apify` to write
        an empty override would be ceremony. Make it abstract if a provider ever
        leaks by forgetting to implement it.
        """

    async def __aenter__(self) -> CandidateProvider:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
