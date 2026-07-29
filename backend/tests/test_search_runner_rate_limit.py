"""What the search pipeline does when the hourly scrape budget runs out.

Running out mid-search is the *expected* outcome for any search bigger than the
cap, not an error — so it must land as a completed search holding the profiles
that were collected, never as a failure that throws them away.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.enums import SearchStatus
from app.db.models import Search, SearchResult
from app.db.session import SessionLocal
from app.domain.models import RawProfile, SearchHit
from app.providers.base import CandidateProvider
from app.providers.rate_limit import LimiterSnapshot, RateLimitExceeded
from app.schemas.search import SearchCreate
from app.services import search_runner, search_service
from app.services.user_service import ensure_user

USER_ID = "00000000-0000-0000-0000-000000000001"


class _BudgetedProvider(CandidateProvider):
    """Serves ``budget`` profiles, then behaves like a spent rate limiter."""

    name = "linkedin"

    def __init__(self, *, hits: int, budget: int) -> None:
        self._hits = hits
        self._budget = budget
        self.fetched = 0

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
        if self.fetched >= self._budget:
            raise RateLimitExceeded("budget spent", retry_after_s=1800)
        self.fetched += 1
        return RawProfile(
            source=self.name,
            source_profile_url=hit.source_profile_url,
            name=hit.name or "Unknown",
            headline="Backend Engineer",
            skills=["python", "fastapi"],
        )

    def budget(self) -> LimiterSnapshot:
        return LimiterSnapshot(used=0, limit=20, window_s=3600.0, resets_in_s=0.0)


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


def test_running_out_of_budget_keeps_what_was_collected(_provider):
    provider = _provider(_BudgetedProvider(hits=10, budget=4))
    db = SessionLocal()
    try:
        search = _make_search(db, max_results=10)
        asyncio.run(search_runner.execute_search(search.id))

        db.refresh(search)
        assert search.status == SearchStatus.COMPLETED
        assert search.error is None
        # The four profiles fetched before the limiter bit are stored and ranked.
        results = db.query(SearchResult).filter_by(search_id=search.id).all()
        assert len(results) == 4
        assert provider.fetched == 4
    finally:
        db.close()


def test_progress_explains_why_the_search_stopped(_provider):
    _provider(_BudgetedProvider(hits=10, budget=3))
    db = SessionLocal()
    try:
        search = _make_search(db, max_results=10)
        asyncio.run(search_runner.execute_search(search.id))

        db.refresh(search)
        progress = search.progress
        assert progress["rate_limited"] is True
        assert progress["retry_after_s"] == 1800
        # Counted profiles must not include the one the limiter refused.
        assert progress["processed"] == 3
        assert "budget spent" in progress["note"]
    finally:
        db.close()


def test_budget_is_reported_before_the_search_starts(_provider):
    _provider(_BudgetedProvider(hits=2, budget=10))
    db = SessionLocal()
    try:
        search = _make_search(db, max_results=2)
        asyncio.run(search_runner.execute_search(search.id))

        db.refresh(search)
        assert search.status == SearchStatus.COMPLETED
        assert search.progress["budget_limit"] == 20
        assert search.progress["budget_remaining"] == 20
        assert "rate_limited" not in search.progress
    finally:
        db.close()


def test_providers_without_a_budget_report_none(_provider):
    class _Plain(_BudgetedProvider):
        budget = None  # type: ignore[assignment]

    _provider(_Plain(hits=2, budget=10))
    db = SessionLocal()
    try:
        search = _make_search(db, max_results=2)
        asyncio.run(search_runner.execute_search(search.id))

        db.refresh(search)
        assert search.status == SearchStatus.COMPLETED
        assert "budget_limit" not in search.progress
    finally:
        db.close()
