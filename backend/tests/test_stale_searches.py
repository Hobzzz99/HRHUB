"""A search whose worker died must not say "running" forever.

`execute_search` leaves `running` only from inside the process doing the work.
When that process goes away — a closed laptop lid, a killed worker, Chromium out
of memory — nothing writes a terminal status at all, and the recruiter watches a
progress bar that will never move. Scrape-backed runs take minutes, so "still
going" stays plausible indefinitely.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.enums import SearchStatus
from app.db.models import Search
from app.db.session import SessionLocal
from app.schemas.search import SearchCreate
from app.services import search_service, stale_searches
from app.services.user_service import ensure_user

USER_ID = "00000000-0000-0000-0000-000000000001"


def _running_search(db, *, age_s: int) -> Search:
    ensure_user(db, USER_ID, "dev@example.com")
    db.commit()
    search = search_service.create_search(
        db, USER_ID, SearchCreate(job_title="external audit manager", provider="linkedin")
    )
    search.status = SearchStatus.RUNNING
    # updated_at is what the sweep measures, and every progress write touches
    # it — so a slow-but-alive search keeps refreshing it.
    search.updated_at = datetime.now(UTC) - timedelta(seconds=age_s)
    db.commit()
    return search


def test_an_abandoned_search_is_marked_failed():
    db = SessionLocal()
    try:
        search = _running_search(db, age_s=99_999)
        assert stale_searches.sweep(db) == 1

        db.refresh(search)
        assert search.status == SearchStatus.FAILED
        assert search.completed_at is not None
        assert "stopped unexpectedly" in (search.error or "")
    finally:
        db.close()


def test_the_message_says_the_work_is_not_lost():
    """Re-running reuses cached profiles, so the budget is not spent twice."""
    db = SessionLocal()
    try:
        search = _running_search(db, age_s=99_999)
        stale_searches.sweep(db)
        db.refresh(search)
        assert "re-running" in (search.error or "").lower()
    finally:
        db.close()


def test_a_search_that_is_merely_slow_is_left_alone():
    """Scrape runs legitimately take minutes; reaping one mid-flight would
    mark a working search failed and orphan its browser."""
    db = SessionLocal()
    try:
        search = _running_search(db, age_s=30)
        assert stale_searches.sweep(db) == 0

        db.refresh(search)
        assert search.status == SearchStatus.RUNNING
    finally:
        db.close()


def test_finished_searches_are_never_touched():
    db = SessionLocal()
    try:
        search = _running_search(db, age_s=99_999)
        search.status = SearchStatus.COMPLETED
        db.commit()

        assert stale_searches.sweep(db) == 0
        db.refresh(search)
        assert search.status == SearchStatus.COMPLETED
        assert search.error is None
    finally:
        db.close()


def test_sweeping_an_empty_table_is_a_no_op():
    db = SessionLocal()
    try:
        assert stale_searches.sweep(db) == 0
    finally:
        db.close()
