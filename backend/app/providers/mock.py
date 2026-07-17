"""Deterministic mock provider.

Serves a fixed set of fixture profiles with no network or credentials. This is
the default provider and how the whole app is developed and tested. `search`
simulates a result list; `fetch_profile` returns the full profile for a hit.
"""

from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files

from app.core.logging import get_logger
from app.domain.models import RawProfile, SearchCriteria, SearchHit
from app.providers.base import CandidateProvider, ProfileUnavailableError

logger = get_logger(__name__)


@lru_cache
def _load_fixtures() -> list[RawProfile]:
    text = files("app.providers").joinpath("fixtures/mock_profiles.json").read_text("utf-8")
    return [RawProfile.model_validate(item) for item in json.loads(text)]


class MockProvider(CandidateProvider):
    name = "mock"

    def __init__(self) -> None:
        self._profiles = {p.source_profile_url: p for p in _load_fixtures()}

    async def search(self, criteria: SearchCriteria) -> list[SearchHit]:
        # Simulate a LinkedIn-style result list: return everyone as a card and
        # let the pre-filter + scoring pipeline narrow it down. Cap generously so
        # `max_results` still applies to the final, ranked set downstream.
        hits = [
            SearchHit(
                source_profile_url=p.source_profile_url,
                name=p.name,
                headline=p.headline,
                current_company=p.current_company,
                location=p.location,
            )
            for p in self._profiles.values()
        ]
        logger.info("mock_search", returned=len(hits), job_title=criteria.job_title)
        return hits

    async def fetch_profile(self, hit: SearchHit) -> RawProfile:
        profile = self._profiles.get(hit.source_profile_url)
        if profile is None:
            raise ProfileUnavailableError(f"No mock profile for {hit.source_profile_url}")
        return profile.model_copy(deep=True)
