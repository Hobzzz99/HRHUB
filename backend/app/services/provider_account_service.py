"""Encrypted provider-account session state.

Only used by the opt-in LinkedIn provider, which stores the Playwright
`storage_state` a manual sign-in produced so later searches skip the login.
Everything here is encrypted at rest with Fernet (`app.core.crypto`) and is
never logged. See COMPLIANCE.md.

The **credential** helpers below (`set_credentials` / `decrypt_credentials`) are
no longer read by any provider: sign-in is done by hand, so the app never has a
password to type. They are kept only so the existing `/provider-account`
endpoint keeps its shape. Do not wire them back into the scraper — storing a
LinkedIn password that nothing uses is pure liability.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.core.logging import get_logger
from app.db.enums import ProviderAccountStatus
from app.db.models import ProviderAccount

logger = get_logger(__name__)


def get_account(db: Session, user_id: str, provider: str) -> ProviderAccount | None:
    return db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.user_id == uuid.UUID(str(user_id)),
            ProviderAccount.provider == provider,
        )
    )


def get_or_create_account(db: Session, user_id: str, provider: str) -> ProviderAccount:
    """The row a browser session is stored against, creating it if absent.

    Sign-in is manual, so there are no credentials to create the row as a side
    effect any more. Without this the very first run would have nowhere to save
    its session and would ask the user to log in again on every single search.
    """
    account = get_account(db, user_id, provider)
    if account is not None:
        return account
    account = ProviderAccount(user_id=uuid.UUID(str(user_id)), provider=provider)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def set_credentials(
    db: Session, user_id: str, provider: str, username: str, password: str
) -> ProviderAccount:
    account = get_account(db, user_id, provider)
    if account is None:
        account = ProviderAccount(user_id=uuid.UUID(str(user_id)), provider=provider)
        db.add(account)
    account.encrypted_credentials = encrypt(
        json.dumps({"username": username, "password": password})
    )
    account.status = ProviderAccountStatus.ACTIVE
    db.commit()
    db.refresh(account)
    return account


def decrypt_credentials(account: ProviderAccount | None) -> dict | None:
    if account is None or not account.encrypted_credentials:
        return None
    return json.loads(decrypt(account.encrypted_credentials))


def load_session_state(account: ProviderAccount | None) -> dict | None:
    if account is None or not account.encrypted_session_state:
        return None
    return json.loads(decrypt(account.encrypted_session_state))


def save_session_state(db: Session, account_id: uuid.UUID, state: dict) -> None:
    account = db.get(ProviderAccount, account_id)
    if account is None:
        return
    account.encrypted_session_state = encrypt(json.dumps(state))
    account.last_used_at = datetime.now(timezone.utc)
    db.commit()
