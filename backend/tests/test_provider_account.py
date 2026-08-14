"""Provider-account session storage and the rotation lifecycle."""

from __future__ import annotations

import pytest

from app.db.enums import ProviderAccountStatus
from app.db.session import SessionLocal
from app.services import provider_account_service as svc
from app.services.user_service import ensure_user

USER_ID = "00000000-0000-0000-0000-000000000001"


@pytest.fixture
def db():
    session = SessionLocal()
    try:
        ensure_user(session, USER_ID, "dev@example.com")
        session.commit()
        yield session
    finally:
        session.close()


def test_get_or_create_live_account_is_idempotent(db):
    # Manual sign-in means nothing else creates this row, so the session from a
    # first-ever login would have nowhere to go without it.
    assert svc.get_live_account(db, USER_ID, "scrape-test") is None

    created = svc.get_or_create_live_account(db, USER_ID, "scrape-test")
    again = svc.get_or_create_live_account(db, USER_ID, "scrape-test")
    assert created.id == again.id
    assert created.status == ProviderAccountStatus.ACTIVE


def test_session_state_round_trips_encrypted(db):
    account = svc.get_or_create_live_account(db, USER_ID, "session-test")
    svc.save_session_state(db, account.id, {"cookies": [{"name": "li_at"}]})

    stored = svc.get_live_account(db, USER_ID, "session-test")
    assert "li_at" not in (stored.encrypted_session_state or "")
    assert svc.load_session_state(stored) == {"cookies": [{"name": "li_at"}]}


def test_mark_restricted_drops_the_session(db):
    account = svc.get_or_create_live_account(db, USER_ID, "restrict-test")
    svc.save_session_state(db, account.id, {"cookies": [{"name": "li_at"}]})

    restricted = svc.mark_restricted(db, USER_ID, "restrict-test", "locked out")

    assert restricted.status == ProviderAccountStatus.RESTRICTED
    assert restricted.status_reason == "locked out"
    # A session for a locked account is unusable and is only a liability.
    assert restricted.encrypted_session_state is None


def test_mark_restricted_is_idempotent(db):
    svc.get_or_create_live_account(db, USER_ID, "restrict-twice")
    first = svc.mark_restricted(db, USER_ID, "restrict-twice", "first reason")
    second = svc.mark_restricted(db, USER_ID, "restrict-twice", "second reason")

    assert first.id == second.id
    assert second.status_reason == "first reason"


def test_rotation_issues_a_new_account_with_a_new_fingerprint_seed(db):
    original = svc.get_or_create_live_account(db, USER_ID, "rotate-test")
    svc.save_session_state(db, original.id, {"cookies": [{"name": "li_at"}]})
    svc.mark_restricted(db, USER_ID, "rotate-test", "locked out")
    original_id = original.id

    replacement = svc.rotate_account(db, USER_ID, "rotate-test")

    # A different row id is the whole point: it reseeds the browser fingerprint,
    # so the replacement does not present the retired account's machine.
    assert replacement.id != original_id
    assert replacement.status == ProviderAccountStatus.ACTIVE
    assert replacement.encrypted_session_state is None

    # The live account is now the replacement; the old row survives as history
    # so its id can never be handed out as a fingerprint seed again.
    assert svc.get_live_account(db, USER_ID, "rotate-test").id == replacement.id
    assert db.get(type(original), original_id).status == ProviderAccountStatus.RETIRED


def test_rotation_accumulates_history(db):
    svc.get_or_create_live_account(db, USER_ID, "history-test")
    seeds = set()
    for _ in range(3):
        seeds.add(svc.rotate_account(db, USER_ID, "history-test").id)

    assert len(seeds) == 3, "each rotation must yield a distinct fingerprint seed"
    assert svc.count_retired(db, USER_ID, "history-test") == 3


def test_rotation_works_on_an_active_account(db):
    # An operator who suspects a lock is coming should not have to wait for the
    # platform to confirm it before stepping away.
    original = svc.get_or_create_live_account(db, USER_ID, "early-rotate")
    replacement = svc.rotate_account(db, USER_ID, "early-rotate")
    assert replacement.id != original.id
