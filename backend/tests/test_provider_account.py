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
