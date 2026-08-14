"""Encrypted provider-account session state, and the account rotation lifecycle.

Only used by the opt-in LinkedIn provider, which stores the Playwright
`storage_state` a manual sign-in produced so later searches skip the login.
Everything here is encrypted at rest with Fernet (`app.core.crypto`) and is
never logged. See COMPLIANCE.md.

There are deliberately **no credential helpers**: sign-in is done by hand, so
the app never has a password to type. Do not add them — storing a LinkedIn
password that nothing reads is pure liability.

**Rotation.** A user has one live row per provider plus every row they have
retired. Rotating retires the live row and creates a fresh one. The new row gets
a new `id`, and because `id` seeds the browser fingerprint
(`search_runner._build_provider`), the replacement account presents different
hardware from the account it replaced. Clearing the session on the *same* row
would not do that — it would hand the next account the burned account's machine
identity, which is precisely how platforms link the two.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.crypto import decrypt, encrypt
from app.core.logging import get_logger
from app.core.security import as_user_uuid
from app.db.enums import ProviderAccountStatus
from app.db.models import ProviderAccount

logger = get_logger(__name__)


def get_live_account(
    db: Session, user_id: str, provider: str
) -> ProviderAccount | None:
    """The row currently representing this provider — active or restricted."""
    return db.scalar(
        select(ProviderAccount).where(
            ProviderAccount.user_id == as_user_uuid(user_id),
            ProviderAccount.provider == provider,
            ProviderAccount.status != ProviderAccountStatus.RETIRED,
        )
    )


def get_or_create_live_account(
    db: Session, user_id: str, provider: str
) -> ProviderAccount:
    """The live row for this provider, creating it if there is none.

    Sign-in is manual, so nothing else creates this row. Without it the session
    from a first-ever login would have nowhere to go and every search would ask
    the operator to log in again.
    """
    account = get_live_account(db, user_id, provider)
    if account is not None:
        return account
    return _create_account(db, user_id, provider)


def _create_account(db: Session, user_id: str, provider: str) -> ProviderAccount:
    account = ProviderAccount(user_id=as_user_uuid(user_id), provider=provider)
    db.add(account)
    db.commit()
    db.refresh(account)
    return account


def mark_restricted(
    db: Session, user_id: str, provider: str, reason: str | None = None
) -> ProviderAccount | None:
    """Record that the platform locked this account. Idempotent.

    The stored session is dropped at the same time: it cannot be used again, and
    a session for a locked account is only a liability sitting in the database.
    """
    account = get_live_account(db, user_id, provider)
    if account is None or account.status == ProviderAccountStatus.RESTRICTED:
        return account

    account.status = ProviderAccountStatus.RESTRICTED
    account.status_reason = reason or "Locked by the platform after automated access."
    account.encrypted_session_state = None
    db.commit()
    db.refresh(account)
    logger.warning("provider_account_restricted", provider=provider)
    return account


def rotate_account(db: Session, user_id: str, provider: str) -> ProviderAccount:
    """Retire the live account and return a fresh one to sign in with.

    The new row's id is what makes this a real rotation rather than a reset: it
    reseeds the browser fingerprint, so the replacement account does not present
    the machine that the retired one was seen on.
    """
    current = get_live_account(db, user_id, provider)
    if current is not None:
        current.status = ProviderAccountStatus.RETIRED
        # A retired session can never be reused, and keeping it would leave a
        # usable login for an account we have deliberately walked away from.
        current.encrypted_session_state = None
        db.commit()
        logger.info("provider_account_retired", provider=provider)

    replacement = _create_account(db, user_id, provider)
    logger.info("provider_account_rotated", provider=provider)
    return replacement


def count_retired(db: Session, user_id: str, provider: str) -> int:
    """How many accounts have already been burned on this provider."""
    return len(
        db.scalars(
            select(ProviderAccount.id).where(
                ProviderAccount.user_id == as_user_uuid(user_id),
                ProviderAccount.provider == provider,
                ProviderAccount.status == ProviderAccountStatus.RETIRED,
            )
        ).all()
    )


def load_session_state(account: ProviderAccount | None) -> dict | None:
    if account is None or not account.encrypted_session_state:
        return None
    return json.loads(decrypt(account.encrypted_session_state))


def save_session_state(db: Session, account_id: uuid.UUID, state: dict) -> None:
    account = db.get(ProviderAccount, account_id)
    if account is None:
        return
    account.encrypted_session_state = encrypt(json.dumps(state))
    account.last_used_at = datetime.now(UTC)
    db.commit()
