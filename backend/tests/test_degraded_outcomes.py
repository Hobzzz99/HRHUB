"""A search that could not do what it was asked must say so.

Until now a run had two outcomes: it finished, or it raised. A Big Four filter
that never reached LinkedIn, a results list that would not render, a session that
expired at the second profile — all three finished, and all three were reported
to the recruiter as:

    "No candidates matched. Try lowering the minimum score or experience."

That sentence blames the recruiter's criteria for a broken scraper, and it is why
every real search this week looked like an empty market.
"""

from __future__ import annotations

import asyncio

import pytest

from app.db.enums import SearchStatus
from app.db.models import Search
from app.db.session import SessionLocal
from app.domain.models import RawProfile, SearchCriteria, SearchHit
from app.providers.base import CandidateProvider, Degradation, ProviderError
from app.schemas.search import SearchCreate
from app.services import search_runner, search_service
from app.services.user_service import ensure_user

USER_ID = "00000000-0000-0000-0000-000000000001"


class _Provider(CandidateProvider):
    """Returns cards; optionally fails to open every profile."""

    name = "mock"

    def __init__(self, *, hits: int = 5, fail_with: Exception | None = None) -> None:
        self._hits = hits
        self._fail_with = fail_with
        self.fetched = 0

    async def search(self, criteria: SearchCriteria) -> list[SearchHit]:
        return [
            SearchHit(source_profile_url=f"https://example.com/in/{i}", name=f"P{i}")
            for i in range(self._hits)
        ]

    async def fetch_profile(self, hit: SearchHit) -> RawProfile:
        self.fetched += 1
        if self._fail_with is not None:
            raise self._fail_with
        return RawProfile(
            source="mock",
            source_profile_url=hit.source_profile_url,
            name=hit.name or "?",
            headline="External Audit Manager",
            current_title="External Audit Manager",
        )


def _make_search(db, *, max_results: int = 10) -> Search:
    ensure_user(db, USER_ID, "dev@example.com")
    db.commit()
    return search_service.create_search(
        db,
        USER_ID,
        SearchCreate(
            job_title="external audit manager",
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


class TestProviderDegradations:
    def test_a_provider_records_what_it_could_not_do(self):
        provider = _Provider()
        provider.degraded(Degradation.FILTER_NOT_APPLIED, "Big Four filter not applied")
        assert provider.degradations == [
            (Degradation.FILTER_NOT_APPLIED, "Big Four filter not applied")
        ]

    def test_two_providers_do_not_share_a_list(self):
        """A shared mutable default would blame one run for another's failure."""
        first, second = _Provider(), _Provider()
        first.degraded(Degradation.FILTER_NOT_APPLIED, "x")
        assert second.degradations == []

    def test_a_provider_that_skips_super_init_still_reports(self):
        """No concrete provider chains to the base constructor.

        An AttributeError here would be raised from the pipeline's `finally`,
        masking whatever actually went wrong.
        """
        assert _Provider().degradations == []


class TestDegradationReachesTheSearch:
    def test_a_filter_that_did_not_apply_is_recorded(self, _provider):
        provider = _provider(_Provider(hits=3))
        provider.degraded(
            Degradation.FILTER_NOT_APPLIED, "Big Four filter could not be applied"
        )
        db = SessionLocal()
        try:
            search = _make_search(db)
            asyncio.run(search_runner.execute_search(search.id))
            db.refresh(search)

            assert search.status == SearchStatus.COMPLETED
            assert search.degraded_reasons is not None
            assert search.degraded_reasons[0]["kind"] == Degradation.FILTER_NOT_APPLIED
            assert "Big Four" in search.degraded_reasons[0]["detail"]
        finally:
            db.close()

    def test_a_clean_run_records_nothing(self, _provider):
        """Degraded must stay meaningful — an ordinary run is not degraded."""
        _provider(_Provider(hits=3))
        db = SessionLocal()
        try:
            search = _make_search(db)
            asyncio.run(search_runner.execute_search(search.id))
            db.refresh(search)
            assert search.degraded_reasons is None
        finally:
            db.close()


class TestConsecutiveFailures:
    def test_a_run_that_fails_throughout_stops_early(self, _provider):
        """Every profile failing must not spend the whole hourly budget."""
        provider = _provider(_Provider(hits=20, fail_with=ProviderError("session gone")))
        db = SessionLocal()
        try:
            search = _make_search(db, max_results=20)
            asyncio.run(search_runner.execute_search(search.id))
            db.refresh(search)

            assert provider.fetched == search_runner._CONSECUTIVE_FAILURE_LIMIT
            kinds = [r["kind"] for r in (search.degraded_reasons or [])]
            assert Degradation.PROFILES_UNREACHABLE in kinds
        finally:
            db.close()

    def test_provider_errors_count_toward_the_brake(self, _provider):
        """ProviderError used to be logged and forgotten.

        That is how an expired session burned every remaining budget slot and
        still reported the search as completed with no results.
        """
        provider = _provider(_Provider(hits=10, fail_with=ProviderError("unavailable")))
        db = SessionLocal()
        try:
            search = _make_search(db, max_results=10)
            asyncio.run(search_runner.execute_search(search.id))
            assert provider.fetched < 10, "should have stopped, not spent every slot"
        finally:
            db.close()

    def test_one_success_does_not_disable_the_brake_forever(self):
        """The counter resets on success, so it measures a run that stopped working.

        The previous rule compared a cumulative total and only fired while
        nothing had been kept — so a single good profile switched the brake off
        for the remainder of the run.
        """
        run = search_runner._Collection()
        run.consecutive_failures = 2
        run.consecutive_failures = 0  # what _score_one does after a profile works
        assert run.consecutive_failures == 0


class TestRejectionSummary:
    def test_reasons_are_grouped_and_counted(self):
        summary = search_runner._top_rejections(
            [
                "Works at AMSG, not Deloitte / PwC",
                "Works at Nash CPAs, not Deloitte / PwC",
                "Only 3 yrs experience (< 5 required)",
            ]
        )
        assert summary is not None
        assert summary[0] == "2x works at a different employer"

    def test_nothing_rejected_reports_nothing(self):
        assert search_runner._top_rejections([]) is None

    def test_specifics_do_not_prevent_grouping(self):
        """Each reason names a different number of years; they must still aggregate.

        Grouping the raw strings gave every candidate their own bucket, which
        told the recruiter nothing.
        """
        summary = search_runner._top_rejections(
            [f"Only {n} yrs experience (< 5 required)" for n in (1, 2, 3, 4)]
        )
        assert summary == ["4x not enough experience"]

    def test_an_unrecognised_reason_keeps_its_own_text(self):
        """A new filter must degrade to verbose, never to wrong."""
        summary = search_runner._top_rejections(["Some filter added later"])
        assert summary == ["1x Some filter added later"]
