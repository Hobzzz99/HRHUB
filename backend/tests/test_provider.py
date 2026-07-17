"""Tests for the mock provider and factory."""

from __future__ import annotations

import pytest

from app.domain.models import SearchCriteria, SearchHit
from app.providers.base import ProfileUnavailableError
from app.providers.factory import get_provider
from app.providers.mock import MockProvider


@pytest.mark.asyncio
async def test_factory_returns_mock():
    provider = get_provider("mock")
    assert isinstance(provider, MockProvider)


@pytest.mark.asyncio
async def test_search_returns_hits():
    provider = get_provider("mock")
    hits = await provider.search(SearchCriteria(job_title="Backend Engineer"))
    assert len(hits) >= 10
    assert all(isinstance(h, SearchHit) for h in hits)
    assert all(h.source_profile_url for h in hits)


@pytest.mark.asyncio
async def test_fetch_profile_roundtrips():
    provider = get_provider("mock")
    hits = await provider.search(SearchCriteria(job_title="Backend Engineer"))
    profile = await provider.fetch_profile(hits[0])
    assert profile.name
    assert profile.source == "mock"
    assert isinstance(profile.skills, list)


@pytest.mark.asyncio
async def test_fetch_unknown_profile_raises():
    provider = get_provider("mock")
    with pytest.raises(ProfileUnavailableError):
        await provider.fetch_profile(SearchHit(source_profile_url="https://nope"))


def test_unknown_provider_raises():
    with pytest.raises(ValueError):
        get_provider("does-not-exist")
