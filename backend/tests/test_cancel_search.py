"""A recruiter must be able to stop a search they did not mean to start.

Enter submits the form, so a half-filled search begins on a misclick and then
spends real scrape budget against a real LinkedIn account for several minutes.

Cancelling is not failing: whatever the run had already paid for is kept, which
is why the worker stops *between* profiles rather than being killed.
"""

from __future__ import annotations

import uuid

from app.db.enums import SearchStatus
from app.db.session import SessionLocal
from app.schemas.search import SearchCreate
from app.services import search_service
from app.services.user_service import ensure_user

USER_ID = "00000000-0000-0000-0000-000000000001"
OTHER_USER_ID = "00000000-0000-0000-0000-0000000000ff"


def _search(db, *, status: SearchStatus, user_id: str = USER_ID):
    ensure_user(db, user_id, "dev@example.com")
    db.commit()
    search = search_service.create_search(
        db, user_id, SearchCreate(job_title="audit manager", provider="linkedin")
    )
    search.status = status
    db.commit()
    return search


def test_a_queued_search_stops_immediately():
    """It has not started, so there is nothing to ask and nothing to keep."""
    db = SessionLocal()
    try:
        search = _search(db, status=SearchStatus.QUEUED)
        result = search_service.request_cancel(db, USER_ID, search.id)

        assert result is not None
        assert result.status == SearchStatus.CANCELLED
        assert result.completed_at is not None
        assert "before it started" in (result.error or "")
    finally:
        db.close()


def test_a_running_search_is_asked_rather_than_killed():
    """The worker is on the recruiter's laptop and checks between profiles.

    Killing it mid-profile would waste a slot already charged to the hourly
    budget, which takes an hour to come back.
    """
    db = SessionLocal()
    try:
        search = _search(db, status=SearchStatus.RUNNING)
        result = search_service.request_cancel(db, USER_ID, search.id)

        assert result is not None
        assert result.cancel_requested is True
        assert result.status == SearchStatus.RUNNING, "the worker decides when to stop"
    finally:
        db.close()


def test_a_finished_search_is_left_alone():
    """Cancelling one would rewrite a result the recruiter may be reading."""
    db = SessionLocal()
    try:
        search = _search(db, status=SearchStatus.COMPLETED)
        result = search_service.request_cancel(db, USER_ID, search.id)

        assert result is not None
        assert result.status == SearchStatus.COMPLETED
        assert result.cancel_requested is False
    finally:
        db.close()


def test_one_recruiter_cannot_stop_anothers_search():
    db = SessionLocal()
    try:
        search = _search(db, status=SearchStatus.RUNNING)
        ensure_user(db, OTHER_USER_ID, "other@example.com")
        db.commit()

        assert search_service.request_cancel(db, OTHER_USER_ID, search.id) is None
        db.refresh(search)
        assert search.cancel_requested is False
    finally:
        db.close()


def test_cancelling_a_search_that_does_not_exist():
    db = SessionLocal()
    try:
        assert search_service.request_cancel(db, USER_ID, uuid.uuid4()) is None
    finally:
        db.close()


def test_cancelled_is_a_terminal_state():
    """The live stream must stop polling, and the page must render results."""
    assert SearchStatus.CANCELLED.is_terminal


class TestTheProviderNoticesToo:
    """The runner's profile loop is not the only place a stop must be seen.

    Finding profiles takes one to two minutes against LinkedIn, and it happens
    *before* that loop. A recruiter who stopped a misclicked search used to wait
    the whole of it while nothing noticed.
    """

    def test_a_provider_polls_the_check_it_was_given(self):
        from app.providers.mock import MockProvider

        provider = MockProvider()
        assert provider.cancel_requested() is False

        stopped = False
        provider.set_cancel_check(lambda: stopped)
        assert provider.cancel_requested() is False

        stopped = True
        assert provider.cancel_requested() is True

    def test_a_provider_with_no_check_never_reports_a_cancellation(self):
        """Providers that are never given one must not stop themselves."""
        from app.providers.mock import MockProvider

        assert MockProvider().cancel_requested() is False
