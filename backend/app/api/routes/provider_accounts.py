"""Provider-account status and rotation (opt-in LinkedIn provider only).

`GET` reports whether a browser session has been captured yet, and whether the
platform has locked the account. `POST .../rotate` retires the current account
and issues a fresh one to sign in with.

There is no route to submit credentials: `PROVIDER=linkedin` signs in manually,
so none are ever sent or stored. See COMPLIANCE.md.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.deps import get_authed_user
from app.core.security import CurrentUser
from app.db.enums import ProviderAccountStatus
from app.db.models import ProviderAccount
from app.db.session import get_db
from app.services import provider_account_service

router = APIRouter(prefix="/provider-account", tags=["provider-account"])


class ProviderAccountOut(BaseModel):
    provider: str
    status: str
    has_session: bool
    #: Why the account stopped being usable, when it has.
    status_reason: str | None = None
    #: How many accounts have already been burned on this provider. Surfaced so
    #: the operator sees the pattern rather than only the current failure.
    retired_count: int = 0


def _to_out(account: ProviderAccount, retired_count: int) -> ProviderAccountOut:
    return ProviderAccountOut(
        provider=account.provider,
        status=account.status,
        has_session=bool(account.encrypted_session_state),
        status_reason=account.status_reason,
        retired_count=retired_count,
    )


@router.get("/{provider}", response_model=ProviderAccountOut | None)
def get_account(
    provider: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> ProviderAccountOut | None:
    account = provider_account_service.get_live_account(db, user.id, provider)
    if account is None:
        return None
    return _to_out(
        account, provider_account_service.count_retired(db, user.id, provider)
    )


@router.post("/{provider}/rotate", response_model=ProviderAccountOut)
def rotate_account(
    provider: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> ProviderAccountOut:
    """Retire the current account and issue a fresh one to sign in with.

    Deliberately allowed even when the current account is still active — an
    operator who suspects an account is about to be locked should be able to
    step away from it without waiting for the platform to confirm it.
    """
    replacement = provider_account_service.rotate_account(db, user.id, provider)
    return _to_out(
        replacement, provider_account_service.count_retired(db, user.id, provider)
    )


@router.get("/{provider}/can-search", response_model=bool)
def can_search(
    provider: str,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_authed_user),
) -> bool:
    """Whether a scraping search would run, or be refused as restricted."""
    account = provider_account_service.get_live_account(db, user.id, provider)
    return account is None or account.status != ProviderAccountStatus.RESTRICTED
