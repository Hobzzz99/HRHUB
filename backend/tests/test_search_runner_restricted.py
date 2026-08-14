"""What the search pipeline does when the platform locks the account.

A restriction is terminal and must stop the whole run. The failure mode this
guards against is subtle: `AccountRestrictedError` used to be a `ProviderError`,
which the per-profile handler treats as "skip and continue" — so a locked
account got re-opened once for every remaining profile, which is exactly what
makes a restriction permanent.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.enums import ProviderAccountStatus, SearchStatus
from app.db.models import Search, SearchResult
from app.db.session import SessionLocal
from app.domain.models import RawProfile, SearchHit
from app.providers.base import AccountRestrictedError, CandidateProvider
from app.schemas.search import SearchCreate
from app.services import provider_account_service, search_runner, search_service
from app.services.user_service import ensure_user

USER_ID = "00000000-0000-0000-0000-000000000001"


class _RestrictingProvider(CandidateProvider):
    """Serves profiles until ``restrict_after``, then reports a locked account."""

    name = "linkedin"

    def __init__(self, *, hits: int, restrict_after: int) -> None:
        self._hits = hits
        self._restrict_after = restrict_after
        self.fetch_attempts = 0

    async def search(self, criteria):
        return [
            SearchHit(
                source_profile_url=f"https://www.linkedin.com/in/person-{i}",
                name=f"Person {i}",
                headline="Backend Engineer",
            )
            for i in range(self._hits)
        ]

    async def fetch_profile(self, hit: SearchHit) -> RawProfile:
        self.fetch_attempts += 1
        if self.fetch_attempts > self._restrict_after:
            raise AccountRestrictedError("LinkedIn has RESTRICTED this account")
        return RawProfile(
            source=self.name,
            source_profile_url=hit.source_profile_url,
            name=hit.name or "Unknown",
            headline="Backend Engineer",
            skills=["python", "fastapi"],
        )


def _make_search(db, *, max_results: int) -> Search:
    ensure_user(db, USER_ID, "dev@example.com")
    db.commit()
    return search_service.create_search(
        db,
        USER_ID,
        SearchCreate(
            job_title="Backend Engineer",
            skills=["python"],
            max_results=max_results,
            min_match_score=0.0,
            provider="linkedin",
        ),
    )


@pytest.fixture
def _provider(monkeypatch):
    def install(provider):
        monkeypatch.setattr(search_runner, "_build_provider", lambda db, search: provider)
        return provider

    return install


def test_restriction_stops_the_run_instead_of_skipping_each_profile(_provider):
    provider = _provider(_RestrictingProvider(hits=10, restrict_after=3))
    db = SessionLocal()
    try:
        search = _make_search(db, max_results=10)
        asyncio.run(search_runner.execute_search(search.id))

        # The regression: one attempt past the restriction, not seven more.
        assert provider.fetch_attempts == 4
    finally:
        db.close()


def test_partial_results_survive_a_restriction(_provider):
    _provider(_RestrictingProvider(hits=10, restrict_after=3))
    db = SessionLocal()
    try:
        search = _make_search(db, max_results=10)
        asyncio.run(search_runner.execute_search(search.id))

        db.refresh(search)
        # The run failed, but the profiles already paid for are kept and ranked.
        assert search.status == SearchStatus.FAILED
        assert "RESTRICTED" in search.error
        results = db.query(SearchResult).filter_by(search_id=search.id).all()
        assert len(results) == 3
        assert search.progress["account_restricted"] is True
    finally:
        db.close()


def test_restriction_marks_the_account(_provider):
    _provider(_RestrictingProvider(hits=5, restrict_after=1))
    db = SessionLocal()
    try:
        search = _make_search(db, max_results=5)  # also creates the user row
        provider_account_service.get_or_create_live_account(db, USER_ID, "linkedin")
        asyncio.run(search_runner.execute_search(search.id))

        account = provider_account_service.get_live_account(db, USER_ID, "linkedin")
        assert account.status == ProviderAccountStatus.RESTRICTED
    finally:
        db.close()


def test_a_restricted_account_refuses_to_start_a_new_search():
    """No provider override: the real `_build_provider` must refuse up front."""
    db = SessionLocal()
    try:
        search = _make_search(db, max_results=5)  # also creates the user row
        provider_account_service.get_or_create_live_account(db, USER_ID, "linkedin")
        provider_account_service.mark_restricted(db, USER_ID, "linkedin", "locked")

        asyncio.run(search_runner.execute_search(search.id))

        db.refresh(search)
        assert search.status == SearchStatus.FAILED
        assert "restricted" in search.error.lower()
        # Refused before a browser was ever opened.
        assert search.progress["processed"] == 0
    finally:
        db.close()


def test_rotating_lets_searches_run_again():
    db = SessionLocal()
    try:
        ensure_user(db, USER_ID, "dev@example.com")
        db.commit()
        provider_account_service.get_or_create_live_account(db, USER_ID, "linkedin")
        provider_account_service.mark_restricted(db, USER_ID, "linkedin", "locked")
        provider_account_service.rotate_account(db, USER_ID, "linkedin")

        account = provider_account_service.get_live_account(db, USER_ID, "linkedin")
        assert account.status == ProviderAccountStatus.ACTIVE
    finally:
        db.close()
