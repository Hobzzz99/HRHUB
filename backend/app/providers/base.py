"""The provider interface.

Implementations must return `SearchHit`s from `search` (cheap card data used for
pre-filtering) and a full `RawProfile` from `fetch_profile`. All scoring lives in
`app.domain`, so providers only extract — they never score.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.models import RawProfile, SearchCriteria, SearchHit


class ProviderError(RuntimeError):
    """Base class for recoverable provider failures."""


class ProfileUnavailableError(ProviderError):
    """A specific profile could not be fetched (skip it, keep the search going)."""


class CandidateProvider(ABC):
    """Abstract candidate source."""

    #: Short identifier stored on candidates (e.g. "mock", "linkedin").
    name: str = "base"

    @abstractmethod
    async def search(self, criteria: SearchCriteria) -> list[SearchHit]:
        """Return candidate cards matching the criteria (up to ``max_results``)."""

    @abstractmethod
    async def fetch_profile(self, hit: SearchHit) -> RawProfile:
        """Fetch and extract a full profile for a search hit."""

    async def aclose(self) -> None:
        """Release resources (browser, sessions). Safe no-op by default."""

    async def __aenter__(self) -> "CandidateProvider":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()
