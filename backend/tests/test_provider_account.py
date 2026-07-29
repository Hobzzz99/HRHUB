"""Tests for encrypted provider-account credential storage."""

from __future__ import annotations

from app.db.session import SessionLocal
from app.services import provider_account_service as svc
from app.services.user_service import ensure_user

USER_ID = "00000000-0000-0000-0000-000000000001"


def test_set_and_decrypt_credentials():
    db = SessionLocal()
    try:
        ensure_user(db, USER_ID, "dev@example.com")
        db.commit()
        account = svc.set_credentials(db, USER_ID, "linkedin", "recruiter@x.com", "pw123")
        # Stored value is encrypted, not plaintext.
        assert "pw123" not in (account.encrypted_credentials or "")
        creds = svc.decrypt_credentials(account)
        assert creds == {"username": "recruiter@x.com", "password": "pw123"}
    finally:
        db.close()


def test_get_or_create_account_is_idempotent():
    # Manual sign-in means nothing else creates this row, so the session from a
    # first-ever login would have nowhere to go without it.
    db = SessionLocal()
    try:
        ensure_user(db, USER_ID, "dev@example.com")
        db.commit()
        assert svc.get_account(db, USER_ID, "scrape-test") is None

        created = svc.get_or_create_account(db, USER_ID, "scrape-test")
        again = svc.get_or_create_account(db, USER_ID, "scrape-test")
        assert created.id == again.id
        assert created.encrypted_credentials is None
    finally:
        db.close()


def test_session_state_round_trips_encrypted():
    db = SessionLocal()
    try:
        ensure_user(db, USER_ID, "dev@example.com")
        db.commit()
        account = svc.get_or_create_account(db, USER_ID, "session-test")
        svc.save_session_state(db, account.id, {"cookies": [{"name": "li_at"}]})

        stored = svc.get_account(db, USER_ID, "session-test")
        assert "li_at" not in (stored.encrypted_session_state or "")
        assert svc.load_session_state(stored) == {"cookies": [{"name": "li_at"}]}
    finally:
        db.close()


def test_credentials_endpoint(client):
    resp = client.post(
        "/provider-account",
        json={"provider": "linkedin", "username": "a@b.com", "password": "secret"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["provider"] == "linkedin"
    assert body["has_session"] is False

    got = client.get("/provider-account/linkedin").json()
    assert got["provider"] == "linkedin"
